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
import functools
import requests
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import gradio as gr
from openai import OpenAI

from config import (
    AGENT_NAME,
    BOOKING_HINT,
    CHROMA_PATH,
    USER_NAME,
    USER_TITLE,
)
from ingest import run_ingestion
from context import TWIN_SYSTEM_PROMPT
from tools import tools, handle_tool_calls, db, log_session_turn
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
print(f"\n=== {AGENT_NAME.upper()} STARTUP CHECK ===")
print(f"Agent Name: {AGENT_NAME}")
print(f"Representing: {USER_NAME} ({USER_TITLE})")
print(f"OpenAI API Key: {'✅ Loaded' if os.getenv('OPENAI_API_KEY') else '❌ MISSING'}")
print(f"Telegram Bot: {'✅ Loaded' if os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID') else '⚠️ Not configured (HITL disabled)'}")
print(f"Pushover: {'✅ Loaded' if os.getenv('PUSHOVER_TOKEN') and os.getenv('PUSHOVER_USER') else '⚠️ Not configured'}")
print(f"Database: {'✅ Firestore Connected' if db is not None else 'ℹ️ Local Logging Mode'}")
print("===================================\n")

# Build the knowledge index on first start (e.g. a fresh container) so deploys need no manual step.
if os.getenv("OPENAI_API_KEY") and not os.path.exists(CHROMA_PATH):
    print("📚 No knowledge index found - building it from knowledge/ ...")
    run_ingestion()

MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")

@functools.lru_cache(maxsize=1)
def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception as e:
        print(f"⚠️ OpenAI client initialization error: {e}")
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

def build_system_messages():
    return [{"role": "system", "content": TWIN_SYSTEM_PROMPT + "\n\n" + current_datetime_header()}]

UUID_RE = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'

def check_telegram_for_reply(target_doc_id: str, offset=None):
    """On-demand Telegram poll. Checks for a human reply to target_doc_id."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return None, offset

    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        params = {"timeout": 2, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset

        resp = requests.get(url, params=params, timeout=5).json()
        for update in resp.get("result", []):
            offset = update["update_id"] + 1
            message = update.get("message", {})
            text = message.get("text", "")
            if not text:
                continue

            doc_id = None
            answer = None

            # Strategy 1: Telegram native "Swipe to Reply"
            if "reply_to_message" in message:
                bot_text = message["reply_to_message"].get("text", "")
                match = re.search(f'({UUID_RE})', bot_text)
                if match:
                    doc_id = match.group(1)
                    answer = text

            # Strategy 2: UUID prefix followed by answer
            elif (match := re.search(f'^({UUID_RE})\\s+(.+)', text, re.DOTALL)):
                doc_id = match.group(1)
                answer = match.group(2)

            # Strategy 3: Direct message from authorized user chat ID
            else:
                chat_id_env = os.getenv("TELEGRAM_CHAT_ID")
                sender_id = str(message.get("chat", {}).get("id", ""))
                if chat_id_env and sender_id == str(chat_id_env):
                    doc_id = target_doc_id
                    answer = text

            if doc_id and answer:
                print(f"📥 Caught human reply for {doc_id[:8]}... -> {answer}")
                if db is not None:
                    try:
                        db.collection("escalations").document(doc_id).update({
                            "status": "resolved",
                            "reply": answer
                        })
                    except Exception as e:
                        print(f"Firestore update failed: {e}")

                if doc_id == target_doc_id:
                    return answer, offset
    except Exception as e:
        print(f"⚠️ Telegram check error: {e}")

    return None, offset

def chat(message, history, request=None):
    messages = build_system_messages() + history + [{"role": "user", "content": message}]
    session_hash = getattr(request, "session_hash", None) if request is not None else None
    log_session_turn(session_hash, "user", message)

    client = get_openai_client()
    if not client:
        err = (
            "⚠️ **OpenAI API Key Missing**: Please set `OPENAI_API_KEY` in your `.env` file.\n\n"
            "1. Copy `.env.example` to `.env`:\n"
            "   `cp .env.example .env`\n"
            "2. Open `.env` and set: `OPENAI_API_KEY=sk-...`\n"
            "3. Restart the application: `python app.py`"
        )
        log_session_turn(session_hash, "assistant", err)
        yield err
        return
    
    try:
        response = client.chat.completions.create(model=MODEL_NAME, messages=messages, tools=tools)
    except Exception as e:
        err = f"System error: {str(e)}"
        log_session_turn(session_hash, "assistant", err)
        yield err
        return
        
    max_tool_iterations = 5
    iterations = 0
    
    while response.choices[0].finish_reason == "tool_calls" and iterations < max_tool_iterations:
        message_obj = response.choices[0].message
        tool_calls = message_obj.tool_calls
        
        results = handle_tool_calls(tool_calls)
        
        wait_doc_id = None
        wait_res = None
        for res in results:
            content = json.loads(res["content"])
            if isinstance(content, str) and content.startswith("WAIT_FOR_HUMAN:"):
                wait_doc_id = content.split(":", 1)[1]
                wait_res = res
                break
                
        if wait_doc_id:
            posted_msg = (
                f"✅ Your message has been forwarded directly to {USER_NAME} via Telegram. 📱\n\n"
                "Waiting for a quick reply (up to ~1 minute). "
                "I'll display their response here as soon as it arrives!"
            )
            log_session_turn(session_hash, "assistant", posted_msg)
            yield posted_msg

            waited = 0
            telegram_offset = None

            try:
                bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                if bot_token:
                    seed_resp = requests.get(
                        f"https://api.telegram.org/bot{bot_token}/getUpdates",
                        params={"timeout": 0, "offset": -1},
                        timeout=5
                    ).json()
                    seed_results = seed_resp.get("result", [])
                    if seed_results:
                        telegram_offset = seed_results[-1]["update_id"] + 1
            except Exception:
                pass

            while waited < 20:
                answer, telegram_offset = check_telegram_for_reply(wait_doc_id, telegram_offset)

                if not answer and db is not None:
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
                wait_res["content"] = json.dumps(
                    f"{USER_NAME} did not respond within 1 minute (likely in a meeting or away). "
                    f"The visitor's inquiry WAS forwarded to {USER_NAME} and will be seen. "
                    f"Apologize politely, explain {USER_NAME} is currently away, and offer to take their email "
                    f"via record_user_details so {USER_NAME} can reply personally. {BOOKING_HINT}"
                )
        
        messages.append(message_obj)
        messages.extend(results)
        
        try:
            response = client.chat.completions.create(model=MODEL_NAME, messages=messages, tools=tools)
        except Exception as e:
            err2 = f"System error during tool execution: {str(e)}"
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
                        )
                    )

        gr.HTML(FOOTER_HTML)

    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
        css=CSS,
        js=JS,
        theme=gr.themes.Base(),
    )
