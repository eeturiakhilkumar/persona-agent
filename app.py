try:
    # Chroma needs a newer SQLite than some Linux images ship.
    import sys
    __import__('pysqlite3')
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass

import os
import time
import json
import threading
import functools
from datetime import datetime
from zoneinfo import ZoneInfo
import gradio as gr
from openai import OpenAI

from config import (
    AGENT_NAME,
    BOOKING_HINT,
    CHAT_MESSAGES_PER_IP,
    CHAT_MESSAGES_PER_SESSION,
    CHROMA_PATH,
    INGEST_RUNNING,
    MAX_HISTORY_MESSAGES,
    MAX_MESSAGE_CHARS,
    USER_CALENDAR_URL,
    USER_EMAIL,
    USER_NAME,
    USER_TITLE,
)
from ingest import run_ingestion
from context import TWIN_SYSTEM_PROMPT
from limits import RateLimiter
from telegram_hitl import register_wait, finish_wait, poll_for_reply
from tools import tools, handle_tool_calls, db, log_session_turn, set_escalation_status, redact_secrets
from styles import (
    CSS,
    JS,
    TOP_NAV_HTML,
    HERO_HTML,
    LEFT_SIDEBAR_HTML,
    CHAT_HEADER_HTML,
    INITIAL_CHAT_HTML,
    FOOTER_HTML,
)

# --- STARTUP DIAGNOSTICS ---
_has_pushover = bool(os.getenv('PUSHOVER_TOKEN') and os.getenv('PUSHOVER_USER'))
print(f"\n=== {AGENT_NAME.upper()} STARTUP CHECK ===")
print(f"Agent Name: {AGENT_NAME}")
print(f"Representing: {USER_NAME} ({USER_TITLE})")
print(f"OpenAI API Key: {'✅ Loaded' if os.getenv('OPENAI_API_KEY') else '❌ MISSING - set OPENAI_API_KEY in .env (cp .env.example .env)'}")
print(f"Telegram Bot: {'✅ Loaded' if os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID') else '⚠️ Not configured (HITL disabled)'}")
print(f"Pushover: {'✅ Loaded' if _has_pushover else '⚠️ Not configured'}")
print(f"Database: {'✅ Firestore Connected' if db is not None else 'ℹ️ Local Logging Mode'}")
if db is None and not _has_pushover:
    print("⚠️  WARNING: neither Firestore nor Pushover is configured. Leads are only written to this log,")
    print("    so you will NOT be notified of them. Configure at least one before going public.")
print("===================================\n")

# Build the knowledge index on first start (e.g. a fresh container) in the background, so the server
# starts listening right away. Searches report "still being prepared" until it finishes.
if os.getenv("OPENAI_API_KEY") and not os.path.exists(CHROMA_PATH):
    print("📚 No knowledge index found - building it from knowledge/ in the background ...")
    INGEST_RUNNING.set()
    threading.Thread(target=run_ingestion, daemon=True).start()

MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
# OpenAI rejects an empty tools list, so only send tools when agent.yaml enables some.
_TOOL_ARGS = {"tools": tools} if tools else {}

@functools.lru_cache(maxsize=1)
def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception as e:
        print(f"⚠️ OpenAI client initialization error: {redact_secrets(e)}")
        return None

def current_datetime_header() -> str:
    """Current datetime grounding block for accurate scheduling."""
    tz_str = os.getenv("MEETING_DEFAULT_TIMEZONE", "UTC")
    try:
        local_now = datetime.now(ZoneInfo(tz_str))
    except Exception:
        local_now = datetime.now().astimezone()
    utc_now = local_now.astimezone(ZoneInfo("UTC"))
    return (
        "CURRENT DATE AND TIME (authoritative for all relative date math):\n"
        f"- Local Time ({tz_str}): {local_now.strftime('%A, %B %d, %Y at %I:%M %p %Z')} ({local_now.isoformat()})\n"
        f"- UTC: {utc_now.strftime('%A, %B %d, %Y at %H:%M %Z')} ({utc_now.isoformat()})\n"
        "Rules: 'today' = local date above; 'tomorrow' = local date + 1 day. "
        "Always confirm full date and time before booking."
    )

# Shown to visitors instead of raw exception text, which can contain keys, URLs and internals.
GENERIC_ERROR = "Sorry, something went wrong on my side. Please try again in a moment."
UNAVAILABLE = "Chat is temporarily unavailable. " + (
    f"You can book a call with {USER_NAME} at {USER_CALENDAR_URL}." if USER_CALENDAR_URL
    else f"You can reach {USER_NAME} at {USER_EMAIL}." if USER_EMAIL
    else "Please try again later."
)
MAX_CONCURRENT_CHATS = int(os.getenv("MAX_CONCURRENT_CHATS", "10"))

_session_limiter = RateLimiter(CHAT_MESSAGES_PER_SESSION, 600)
_ip_limiter = RateLimiter(CHAT_MESSAGES_PER_IP, 600)

def build_system_messages():
    return [{"role": "system", "content": TWIN_SYSTEM_PROMPT + "\n\n" + current_datetime_header()}]

def _text_of(content) -> str:
    """Gradio can hand back structured content; the model only needs the text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(_text_of(part) for part in content)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return str(content or "")

def clean_history(history) -> list:
    """Only user/assistant text turns, only the most recent ones: bounds cost and drops stray roles/metadata."""
    cleaned = [
        {"role": turn["role"], "content": _text_of(turn.get("content"))}
        for turn in (history or [])
        if isinstance(turn, dict) and turn.get("role") in ("user", "assistant")
    ]
    return cleaned[-MAX_HISTORY_MESSAGES:]

def _client_ip(request) -> str:
    if request is None:
        return "unknown"
    forwarded = (getattr(request, "headers", None) or {}).get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return getattr(getattr(request, "client", None), "host", None) or "unknown"

def chat(message, history, request: gr.Request = None):
    # The gr.Request annotation is what makes Gradio pass the request in; without it session_hash is always None.
    session_hash = getattr(request, "session_hash", None)

    if not isinstance(message, str):
        message = _text_of(message)
    if len(message) > MAX_MESSAGE_CHARS:
        yield f"That message is too long (limit {MAX_MESSAGE_CHARS} characters). Could you shorten it?"
        return
    if not (_session_limiter.allow(session_hash or "anon") and _ip_limiter.allow(_client_ip(request))):
        yield "You're sending messages very quickly. Please wait a few minutes and try again."
        return

    messages = build_system_messages() + clean_history(history) + [{"role": "user", "content": message}]
    log_session_turn(session_hash, "user", message)

    client = get_openai_client()
    if not client:
        log_session_turn(session_hash, "assistant", UNAVAILABLE)
        yield UNAVAILABLE
        return

    try:
        response = client.chat.completions.create(model=MODEL_NAME, messages=messages, **_TOOL_ARGS)
    except Exception as e:
        print(f"❌ OpenAI request failed: {redact_secrets(e)}")
        err = GENERIC_ERROR
        log_session_turn(session_hash, "assistant", err)
        yield err
        return

    max_tool_iterations = 5
    iterations = 0

    while response.choices[0].finish_reason == "tool_calls" and iterations < max_tool_iterations:
        message_obj = response.choices[0].message
        tool_calls = message_obj.tool_calls

        results = handle_tool_calls(tool_calls, session=session_hash)

        wait_doc_id = None
        wait_res = None
        for res in results:
            content = json.loads(res["content"])
            if isinstance(content, str) and content.startswith("WAIT_FOR_HUMAN:"):
                wait_doc_id = content.split(":", 1)[1]
                wait_res = res
                break

        if wait_doc_id:
            register_wait(wait_doc_id)
            try:
                posted_msg = (
                    f"✅ Your message has been forwarded directly to {USER_NAME} via Telegram. 📱\n\n"
                    "Waiting for a quick reply (up to ~1 minute). "
                    "I'll display their response here as soon as it arrives!"
                )
                log_session_turn(session_hash, "assistant", posted_msg)
                yield posted_msg

                waited = 0
                while waited < 20:
                    answer = poll_for_reply(wait_doc_id)

                    if not answer and db is not None:  # another instance may have caught the reply
                        try:
                            doc = db.collection("escalations").document(wait_doc_id).get().to_dict()
                            if doc and doc.get("status") == "resolved":
                                answer = doc.get("reply")
                        except Exception:
                            pass

                    if answer:
                        wait_res["content"] = json.dumps(f"{USER_NAME} replied: {answer}. Format this nicely for the visitor.")
                        break

                    time.sleep(3)
                    waited += 1
                    if waited % 3 == 0 and waited < 20:
                        progress_msg = (
                            f"✅ Your message was sent to {USER_NAME}. 📱\n\n"
                            f"Still waiting for a response (~{waited * 3}s elapsed). "
                            "Thanks for your patience!"
                        )
                        log_session_turn(session_hash, "assistant", progress_msg)
                        yield progress_msg

                else:
                    set_escalation_status(wait_doc_id, "expired")
                    wait_res["content"] = json.dumps(
                        f"EXPIRED: The question was delivered to {USER_NAME} on Telegram, but no reply arrived within 1 minute, "
                        f"and a late reply will NOT appear in this chat. Do not promise a reply time or say {USER_NAME} will answer here. "
                        f"Apologize politely, explain {USER_NAME} seems to be away, and offer to take the visitor's email "
                        f"via record_user_details so {USER_NAME} can reply personally. {BOOKING_HINT}"
                    )
            finally:
                finish_wait(wait_doc_id)

        messages.append(message_obj)
        messages.extend(results)

        try:
            response = client.chat.completions.create(model=MODEL_NAME, messages=messages, **_TOOL_ARGS)
        except Exception as e:
            print(f"❌ OpenAI request failed after tool call: {redact_secrets(e)}")
            err2 = GENERIC_ERROR
            log_session_turn(session_hash, "assistant", err2)
            yield err2
            return

        iterations += 1

    if iterations >= max_tool_iterations:
        stuck = "I encountered an issue processing that. What else would you like to discuss?"
        log_session_turn(session_hash, "assistant", stuck)
        yield stuck
        return

    final_text = response.choices[0].message.content
    log_session_turn(session_hash, "assistant", final_text)
    yield final_text

if __name__ == "__main__":
    with gr.Blocks() as demo:
        gr.HTML(TOP_NAV_HTML)
        gr.HTML(HERO_HTML)

        with gr.Row(elem_classes="dashboard-grid"):
            # Left Sidebar
            with gr.Column(elem_classes="left-col", scale=4):
                gr.HTML(LEFT_SIDEBAR_HTML)

            # Right Chat Area
            with gr.Column(elem_classes="right-col", scale=8):
                gr.HTML(CHAT_HEADER_HTML)

                with gr.Column(elem_classes="chat-wrapper"):
                    gr.HTML(INITIAL_CHAT_HTML, elem_classes="initial-state-container")

                    gr.ChatInterface(
                        chat,
                        chatbot=gr.Chatbot(
                            show_label=False,
                            elem_classes="native-chatbot"
                        ),
                        # Gradio's default is 1, which makes every visitor wait for the previous one
                        # (a Telegram escalation alone can hold a slot for ~60s).
                        concurrency_limit=MAX_CONCURRENT_CHATS,
                    )

        gr.HTML(FOOTER_HTML)

    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
        css=CSS,
        js=JS,
        theme=gr.themes.Base(),
    )
