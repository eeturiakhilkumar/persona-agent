import json
import os
import requests
import re
import uuid
import functools
import threading
from html import escape
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import firebase_admin
from firebase_admin import credentials, firestore
from pydantic import BaseModel, Field, create_model
from typing import Literal

from config import (
    AGENT,
    AGENT_NAME,
    BASE_DIR,
    BOOKING_HINT,
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBED_MODEL,
    INGEST_RUNNING,
    MEETING_END_HOUR,
    MEETING_MAX_DAYS_AHEAD,
    MEETING_MAX_MINUTES,
    MEETING_START_HOUR,
    MEETING_WORKDAYS_ONLY,
    USER_NAME,
    USER_EMAIL,
    USER_CALENDAR_URL,
)
from limits import RateLimiter

# Which visitor session the tool call belongs to (set by handle_tool_calls; tools run synchronously in that thread).
_ctx = threading.local()

def _session_key() -> str:
    return getattr(_ctx, "session", None) or "anon"

# Per-visitor and global ceilings so a public agent can't be used to spam you, your calendar or Telegram.
_lead_limiter = RateLimiter(10, 3600)
_escalation_session_limiter = RateLimiter(2, 1800)
_escalation_global_limiter = RateLimiter(5, 3600)
_meeting_session_limiter = RateLimiter(2, 3600)
_meeting_global_limiter = RateLimiter(10, 3600)

_SECRET_ENV_VARS = ("TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY", "PUSHOVER_TOKEN", "PUSHOVER_USER")

def redact_secrets(value) -> str:
    """Text safe to log: HTTP errors from `requests` embed the full URL, which for Telegram contains the bot token."""
    text = str(value)
    for name in _SECRET_ENV_VARS:
        secret = os.getenv(name)
        if secret and len(secret) >= 6:
            text = text.replace(secret, "<redacted>")
    text = re.sub(r"/bot\d+:[A-Za-z0-9_-]+", "/bot<redacted>", text)
    return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-<redacted>", text)

pushover_user = os.getenv("PUSHOVER_USER")
pushover_token = os.getenv("PUSHOVER_TOKEN")
pushover_url = "https://api.pushover.net/1/messages.json"

def push(message: str, title: str = f"{AGENT_NAME} Alert"):
    """Send a Pushover alert. Returns True/False for delivered/failed, or None if Pushover isn't configured."""
    if not pushover_token or not pushover_user:
        return None
    try:
        resp = requests.post(pushover_url, data={
            "token": pushover_token,
            "user": pushover_user,
            "message": message,
            "title": title,
            "html": 1
        }, timeout=10)
        if resp.status_code != 200:
            print(f"Push notification rejected (HTTP {resp.status_code})")
        return resp.status_code == 200
    except Exception as e:
        print(f"Push notification failed: {redact_secrets(e)}")
        return False

# Initialize Firebase Admin SDK with graceful local fallback
db = None
try:
    if not firebase_admin._apps:
        firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        if firebase_creds_json:
            cred_dict = json.loads(firebase_creds_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
        else:
            cert_path = os.path.join(BASE_DIR, "serviceAccountKey.json")
            if os.path.exists(cert_path):
                cred = credentials.Certificate(cert_path)
                firebase_admin.initialize_app(cred)
                db = firestore.client()
    else:
        db = firestore.client()
except Exception as e:
    print(f"ℹ️ Firebase initialization skipped ({e}). Operating in local logging mode.")

def notify_and_store(collection_name: str, payload: dict, push_title: str, push_html_message: str) -> str:
    """Persist and announce a handoff. Returns what REALLY happened:
    'delivered'      - saved to Firestore and/or the Pushover alert went out
    'logged_locally' - no database or alerts configured; only the server log has it
    'failed'         - a channel is configured but nothing got through
    """
    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    payload["status"] = "new"

    stored = False
    if db is not None:
        try:
            db.collection(collection_name).add(payload)
            stored = True
        except Exception as e:
            print(f"❌ Firestore Error: {str(e)}")
    else:
        print(f"📝 [Local Log - {collection_name}] {json.dumps(payload)}")

    notified = push(push_html_message, title=push_title)

    if stored or notified:
        return "delivered"
    if db is None and notified is None:
        return "logged_locally"
    print(f"❌ Handoff FAILED for {collection_name}: {json.dumps(payload)}")
    return "failed"

def _handoff_result(outcome: str, ok_text: str) -> str:
    """Turn a handoff outcome into a tool result the model cannot misread as success."""
    if outcome == "delivered":
        return f"OK: {ok_text}"
    if outcome == "logged_locally":
        return (
            f"LOGGED_LOCALLY: The details were written to the server log only (no database or alerts are configured), "
            f"so {USER_NAME} has NOT been notified. Tell the visitor their details were noted but do not promise a reply. {BOOKING_HINT}"
        )
    return (
        f"NOT_SAVED: Saving and notifying {USER_NAME} failed. Do NOT tell the visitor their details were saved or that "
        f"{USER_NAME} will follow up. Apologize briefly and point them to another way to reach {USER_NAME}. {BOOKING_HINT}"
    )

def _too_many_submissions():
    """Return a NOT_SAVED message if this visitor session is submitting too much, else None."""
    if _lead_limiter.allow(_session_key()):
        return None
    return (
        "NOT_SAVED: This visitor has submitted too many forms in a short time. Do NOT claim anything was saved. "
        f"Politely ask them to try again later. {BOOKING_HINT}"
    )

def _missing_info(what: str) -> str:
    return f"NOT_SAVED: {what} Ask the visitor for it. Do not claim anything was saved."

_EMPTY_VALUES = {"", "not provided", "name not provided", "unknown", "n/a", "none"}

def _has_value(value) -> bool:
    return str(value or "").strip().lower() not in _EMPTY_VALUES

def set_escalation_status(escalation_id: str, status: str, **fields):
    """Move an escalation through pending -> delivered -> resolved | expired (or failed), with a timestamp."""
    if db is None:
        return
    try:
        db.collection("escalations").document(escalation_id).update(
            {"status": status, f"{status}_at": datetime.now(timezone.utc).isoformat(), **fields}
        )
    except Exception as e:
        print(f"Escalation status update ({status}) failed: {e}")

def log_session_turn(session_hash, role: str, content: str):
    """Append one chat turn to the per-session transcript record in Firestore if available."""
    if not session_hash or not content or db is None:
        return
    try:
        text = str(content)[:4000]
        entry = {
            "role": role,
            "content": text,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        ref = db.collection("chat_sessions").document(str(session_hash))
        snap = ref.get()
        if snap.exists:
            data = snap.to_dict() or {}
            turns = data.get("turns", [])
            turns.append(entry)
            ref.update({
                "turns": turns[-200:],
                "turn_count": len(turns[-200:]),
                "last_interaction_at": entry["at"],
            })
        else:
            ref.set({
                "session_id": str(session_hash),
                "started_at": entry["at"],
                "last_interaction_at": entry["at"],
                "turn_count": 1,
                "turns": [entry],
            })
    except Exception as e:
        print(f"⚠️ Session log failed: {e}")

def record_user_details(email: str, name: str = "Name not provided", notes: str = "not provided"):
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (email or "").strip()):
        return _missing_info("A valid email address is required to record contact details.")
    if (limited := _too_many_submissions()):
        return limited
    payload = {"email": email, "name": name, "notes": notes}
    title = f"✉️ Contact Request for {USER_NAME}"
    msg = f"<b>Name:</b> {escape(name)}<br><b>Email:</b> {escape(email)}<br><b>Notes:</b> {escape(notes)}"
    return _handoff_result(notify_and_store("general_contacts", payload, title, msg), "Contact details recorded successfully.")

def record_unknown_question(question: str):
    if not _has_value(question):
        return _missing_info("The question text is empty.")
    if (limited := _too_many_submissions()):
        return limited
    payload = {"question": question}
    title = f"❓ Unknown Question for {USER_NAME}"
    msg = f"<b>Question:</b> {escape(question)}"
    return _handoff_result(notify_and_store("unknown_questions", payload, title, msg), "Question logged for review.")

def _label(field_name: str) -> str:
    return field_name.replace("_", " ").title()

def _make_lead_tool(form: dict):
    """Build the callable behind one `lead_forms` entry of agent.yaml."""
    fields = form["fields"]

    def lead_tool(**kwargs):
        values = {}
        for f in fields:
            value = kwargs.get(f["name"], f["default"])
            values[f["name"]] = value if isinstance(value, str) else str(value)
        for f in fields:
            value = values[f["name"]]
            if f["required"] and not _has_value(value):
                return _missing_info(f"'{_label(f['name'])}' is required.")
            if f["min_chars"] and len(value.strip()) < f["min_chars"]:
                return _missing_info(f"'{_label(f['name'])}' is missing or too short to be useful.")
        if form["require_any"] and not any(_has_value(values[n]) for n in form["require_any"]):
            return _missing_info(f"Not enough details were given (need at least one of: {', '.join(form['require_any'])}).")
        if (limited := _too_many_submissions()):
            return limited
        title = f"{form['title']} for {USER_NAME}"
        msg = "<br>".join(f"<b>{escape(_label(n))}:</b> {escape(v)}" for n, v in values.items())
        return _handoff_result(notify_and_store(form["collection"], dict(values), title, msg), form["success_message"])

    lead_tool.__name__ = form["name"]
    return lead_tool

@functools.lru_cache(maxsize=1)
def _get_collection():
    """Open the Chroma collection once; only called after the index exists, so a later `ingest.py` still works."""
    import chromadb
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    embedding_function = OpenAIEmbeddingFunction(api_key=os.environ.get("OPENAI_API_KEY"), model_name=EMBED_MODEL)
    return client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=embedding_function)

def query_project_knowledge_base(query: str):
    if INGEST_RUNNING.is_set():
        return "The knowledge base is still being prepared. Answer from the profile summary and suggest asking again in a minute."
    if not os.path.exists(CHROMA_PATH):
        return "Knowledge base has not been initialized. No indexed documents found."
    for attempt in (1, 2):
        try:
            results = _get_collection().query(query_texts=[query], n_results=3)
            if not results["documents"] or not results["documents"][0]:
                return "No relevant context found in the knowledge base."
            return "\n\n---\n\n".join(results["documents"][0])
        except Exception as e:
            if attempt == 1:
                # `python ingest.py` replaces the collection, which invalidates our cached handle - reopen once.
                _get_collection.cache_clear()
                continue
            print(f"Knowledge retrieval failed: {redact_secrets(e)}")
            return "Knowledge retrieval is temporarily unavailable. Answer from the profile summary only and say you could not check the documents."

def escalate_to_human(question: str):
    # Spam safeguard: check recent escalations if db exists
    if db is not None:
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter
            one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            recent = db.collection("escalations").where(
                filter=FieldFilter("timestamp", ">", one_hour_ago)
            ).get()
            if len(recent) >= 5:
                booking_msg = f" You can also schedule directly at {USER_CALENDAR_URL}" if USER_CALENDAR_URL else ""
                return f"{USER_NAME} is currently busy. Politely let the visitor know and ask for their email via record_user_details so {USER_NAME} can respond later.{booking_msg}"
        except Exception as e:
            print(f"Rate limit check failed: {e}")

    if not _has_value(question):
        return _missing_info("The question to forward is empty.")

    # In-memory limits also protect you when Firestore isn't configured.
    if not (_escalation_session_limiter.allow(_session_key()) and _escalation_global_limiter.allow("all")):
        booking_msg = f" You can also schedule directly at {USER_CALENDAR_URL}" if USER_CALENDAR_URL else ""
        return f"{USER_NAME} is currently busy. Politely let the visitor know and ask for their email via record_user_details so {USER_NAME} can respond later.{booking_msg}"

    escalation_id = str(uuid.uuid4())
    payload = {
        "question": question,
        "status": "pending",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reply": ""
    }
    
    if db is not None:
        try:
            db.collection("escalations").document(escalation_id).set(payload)
        except Exception:
            pass

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    telegram_confirmed = False
    if bot_token and chat_id:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                # Plain text on purpose: visitor text with _ or * would break Markdown parsing.
                "text": f"🚨 {AGENT_NAME} Escalation\n\nUser asked: {question}\n\nEscalation ID: {escalation_id}\n\nReply directly to this message to answer.",
            }
            resp = requests.post(url, json=data, timeout=15)
            try:
                telegram_confirmed = resp.json().get("ok", False)
            except Exception:
                telegram_confirmed = resp.status_code == 200
        except Exception as e:
            print(f"❌ Telegram Error: {redact_secrets(e)}")

    if telegram_confirmed:
        set_escalation_status(escalation_id, "delivered")
    else:
        set_escalation_status(escalation_id, "failed", failure="telegram_not_confirmed")
        booking_link = f" You can also book a call directly at {USER_CALENDAR_URL}." if USER_CALENDAR_URL else (f" You can reach {USER_NAME} directly at {USER_EMAIL}." if USER_EMAIL else "")
        return (
            f"Direct ping to {USER_NAME} is currently unavailable. Please explain that {USER_NAME} cannot be reached "
            f"right this second, ask for the visitor's email via record_user_details so {USER_NAME} can follow up personally.{booking_link}"
        )

    return f"WAIT_FOR_HUMAN:{escalation_id}"

def get_calendar_service():
    """Initializes Google Calendar API client using Service Account credentials."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
    except ImportError:
        raise ImportError("google-api-python-client or google-auth is not installed.")

    creds_json = os.getenv("GOOGLE_CALENDAR_CREDENTIALS_JSON")
    scopes = ["https://www.googleapis.com/auth/calendar"]
    owner_email = os.getenv("GOOGLE_CALENDAR_OWNER_EMAIL")

    if creds_json:
        creds_info = json.loads(creds_json)
        credentials_obj = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
    else:
        cert_path = os.path.join(BASE_DIR, "calendar_service_account.json")
        if not os.path.exists(cert_path):
            raise FileNotFoundError("Calendar credentials not found.")
        credentials_obj = service_account.Credentials.from_service_account_file(cert_path, scopes=scopes)

    if owner_email:
        credentials_obj = credentials_obj.with_subject(owner_email)

    return build("calendar", "v3", credentials=credentials_obj)

def _parse_meeting_start(start_iso: str, now=None):
    default_tz = ZoneInfo(os.getenv("MEETING_DEFAULT_TIMEZONE", "UTC"))
    if now is None:
        now = datetime.now(default_tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=default_tz)

    text = (start_iso or "").strip()
    low = text.lower().strip()

    def _at_time(base_day, time_part):
        tp = (time_part or "").strip().lower().replace(".", "")
        m = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:utc|gmt)?\s*$", tp)
        if not m:
            return None
        hh, mm, ap = m.groups()
        hh, mm = int(hh), int(mm or 0)
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        return base_day.replace(hour=hh, minute=mm, second=0, microsecond=0)

    rel_match = re.match(
        r"^(today|tonight|tomorrow|day after tomorrow|day-after-tomorrow)"
        r"(?:\s+(?:at|around|by)\s+(.+))?$", low)
    if rel_match:
        word, tpart = rel_match.groups()
        base = now
        if word == "tomorrow":
            base = now + timedelta(days=1)
        elif word in ("day after tomorrow", "day-after-tomorrow"):
            base = now + timedelta(days=2)
        base_day = base.replace(hour=9, minute=0, second=0, microsecond=0)
        if tpart:
            dt = _at_time(base_day, tpart)
            if dt is None:
                raise ValueError(f"Could not parse time '{tpart}' in '{start_iso}'.")
            return dt
        return base_day

    iso_text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz)
        return dt
    except ValueError:
        pass

    human_formats = [
        "%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d",
        "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M",
        "%b %d, %Y %H:%M", "%B %d, %Y %H:%M",
        "%b %d, %Y %I:%M %p", "%B %d, %Y %I:%M %p",
    ]
    for fmt in human_formats:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=default_tz)
        except ValueError:
            continue

    raise ValueError(f"Could not understand meeting time '{start_iso}'. Please provide a clear date and time (e.g. '2026-11-15 15:00 UTC').")

def schedule_google_calendar_meeting(attendee_email: str, attendee_name: str, topic: str, start_iso: str, duration_minutes: int = 30):
    """Schedules a meeting directly on the user's Google Calendar with an automatic Google Meet video link."""
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    booking_fallback = BOOKING_HINT

    try:
        start_dt = _parse_meeting_start(start_iso)
    except ValueError as e:
        return str(e)
        
    now = datetime.now(timezone.utc)
    if start_dt < now - timedelta(minutes=1):
        return f"The requested time {start_dt.strftime('%Y-%m-%d %H:%M %Z')} is in the past. Please ask for a future date and time."
    if start_dt > now + timedelta(days=MEETING_MAX_DAYS_AHEAD):
        return f"Meetings can only be booked up to {MEETING_MAX_DAYS_AHEAD} days ahead. Ask the visitor for an earlier date."

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (attendee_email or "").strip()):
        return "A valid attendee email address is required before scheduling. Please ask the visitor for their email."
    attendee_email = attendee_email.strip()

    minutes = duration_minutes or 30
    if not 15 <= minutes <= MEETING_MAX_MINUTES:
        return f"Meetings must be between 15 and {MEETING_MAX_MINUTES} minutes. Ask the visitor to pick a length in that range."
    end_dt = start_dt + timedelta(minutes=minutes)

    # Only offer slots in the owner's working window (in MEETING_DEFAULT_TIMEZONE).
    tz_name = os.getenv("MEETING_DEFAULT_TIMEZONE", "UTC")
    local_start, local_end = start_dt.astimezone(ZoneInfo(tz_name)), end_dt.astimezone(ZoneInfo(tz_name))
    minutes_of_day = lambda d: d.hour * 60 + d.minute
    in_window = (
        local_start.date() == local_end.date()
        and minutes_of_day(local_start) >= MEETING_START_HOUR * 60
        and minutes_of_day(local_end) <= MEETING_END_HOUR * 60
    )
    if not in_window or (MEETING_WORKDAYS_ONLY and local_start.weekday() >= 5):
        days = "on weekdays " if MEETING_WORKDAYS_ONLY else ""
        return (
            f"{USER_NAME} only takes meetings {days}between {MEETING_START_HOUR:02d}:00 and {MEETING_END_HOUR:02d}:00 ({tz_name}). "
            "Ask the visitor for a time inside that window."
        )

    if not (_meeting_session_limiter.allow(_session_key()) and _meeting_global_limiter.allow("all")):
        return f"Too many booking attempts right now. Do not book anything. {booking_fallback}"

    # These go into the invitation email, so keep them short and single-line.
    attendee_name = " ".join((attendee_name or "Guest").split())[:80]
    topic = " ".join((topic or "Intro call").split())[:200]

    try:
        service = get_calendar_service()
    except Exception as e:
        return f"Automated calendar booking is currently not configured ({str(e)[:120]}). {booking_fallback}"

    try:
        busy_info = service.freebusy().query(body={
            "timeMin": start_dt.isoformat(),
            "timeMax": end_dt.isoformat(),
            "items": [{"id": calendar_id}],
        }).execute()
        if next(iter(busy_info.get("calendars", {}).values()), {}).get("busy"):
            return f"{USER_NAME} is already busy at that time. Ask the visitor for another time."
    except Exception as e:
        print(f"Free/busy check skipped: {redact_secrets(e)}")

    event = {
        "summary": f"Meeting: {attendee_name} & {USER_NAME} - {topic}",
        "description": f"Scheduled by {AGENT_NAME}.\n\nAttendee: {attendee_name} ({attendee_email})\nTopic: {topic}",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": str(start_dt.tzinfo)},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": str(end_dt.tzinfo)},
        "attendees": [
            {"email": attendee_email, "displayName": attendee_name}
        ],
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"}
            }
        }
    }

    try:
        try:
            created_event = service.events().insert(
                calendarId=calendar_id,
                body=event,
                conferenceDataVersion=1,
                sendUpdates="all"
            ).execute()
        except Exception:
            plain_event = {k: v for k, v in event.items() if k != "conferenceData"}
            created_event = service.events().insert(
                calendarId=calendar_id,
                body=plain_event,
                sendUpdates="all"
            ).execute()

        meet_link = created_event.get("hangoutLink", "Video link attached in calendar invitation")

        payload = {
            "attendee_email": attendee_email,
            "attendee_name": attendee_name,
            "topic": topic,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "meet_link": meet_link,
            "event_id": created_event.get("id"),
            "event_link": created_event.get("htmlLink", "")
        }
        notify_and_store(
            "scheduled_meetings",
            payload,
            f"📅 Meeting Scheduled with {USER_NAME}",
            f"<b>Attendee:</b> {escape(attendee_name)} ({escape(attendee_email)})<br><b>Time:</b> {start_dt.strftime('%Y-%m-%d %H:%M %Z')}<br><b>Topic:</b> {escape(topic)}<br><b>Meet:</b> {escape(meet_link)}"
        )

        return (
            f"Successfully booked meeting for {start_dt.strftime('%A, %Y-%m-%d %H:%M %Z')} "
            f"({minutes} min). Google Meet Link: {meet_link}. "
            f"A calendar invitation has been sent to {attendee_email} and {USER_NAME}."
        )
    except Exception as e:
        return f"Calendar booking failed ({str(e)[:150]}). {booking_fallback}"

class RecordUserDetails(BaseModel):
    """Record contact details and a message from a visitor."""
    email: str
    name: str = "Name not provided"
    notes: str = "not provided"

class RecordUnknownQuestion(BaseModel):
    """Record a question you do not know the answer to so the user can review and update their knowledge base."""
    question: str

class QueryProjectKnowledgeBase(BaseModel):
    """Search the vector database for contextual information about the user's background, work, documents and policies."""
    query: str

class EscalateToHuman(BaseModel):
    """Use this ONLY when the user asks a highly specific, important question that you do not know and requires direct human input."""
    question: str

class ScheduleGoogleCalendarMeeting(BaseModel):
    """Schedule a meeting directly on the user's Google Calendar with Google Meet. Call ONLY when you have attendee email, name, topic, and confirmed date/time."""
    attendee_email: str
    attendee_name: str
    topic: str
    start_iso: str
    duration_minutes: int = 30

def _to_snake_case(name: str) -> str:
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def pydantic_to_openai_schema(model_class: type[BaseModel], name: str = None) -> dict:
    schema = model_class.model_json_schema()
    parameters = {"type": "object", "properties": schema.get("properties", {}), "additionalProperties": False}
    if "required" in schema: parameters["required"] = schema["required"]
    return {"type": "function", "function": {
        "name": name or _to_snake_case(model_class.__name__),
        "description": schema.get("description", ""),
        "parameters": parameters,
    }}

def _form_model(form: dict) -> type[BaseModel]:
    """Turn a `lead_forms` entry of agent.yaml into a pydantic model (and so a tool schema)."""
    definitions = {}
    for f in form["fields"]:
        annotation = Literal[tuple(f["choices"])] if f["choices"] else str
        description = f["description"] or None
        default = ... if f["required"] else f["default"]
        definitions[f["name"]] = (annotation, Field(default, description=description))
    return create_model("".join(p.title() for p in form["name"].split("_")), __doc__=form["description"], **definitions)

# Tools are assembled from agent.yaml: built-ins follow `features`, lead tools come from `lead_forms`.
tools = []
tool_map = {}

def _register(model, func, name=None):
    schema = pydantic_to_openai_schema(model, name)
    tools.append(schema)
    tool_map[schema["function"]["name"]] = func

if AGENT["features"]["contact_capture"]:
    _register(RecordUserDetails, record_user_details)
    _register(RecordUnknownQuestion, record_unknown_question)
for _form in AGENT["lead_forms"]:
    _register(_form_model(_form), _make_lead_tool(_form), _form["name"])
if AGENT["features"]["knowledge_base"]:
    _register(QueryProjectKnowledgeBase, query_project_knowledge_base)
if AGENT["features"]["escalation"]:
    _register(EscalateToHuman, escalate_to_human)
if AGENT["features"]["scheduling"]:
    _register(ScheduleGoogleCalendarMeeting, schedule_google_calendar_meeting)

def handle_tool_calls(tool_calls, session=None):
    _ctx.session = session
    results = []
    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            results.append({"role": "tool", "content": json.dumps("Error: Invalid JSON arguments"), "tool_call_id": tool_call.id})
            continue
        tool = tool_map.get(tool_name)
        try:
            result = tool(**arguments) if tool else f"Unknown tool: {tool_name}"
        except Exception as e:
            result = f"Tool execution failed: {str(e)}"
        results.append({"role": "tool", "content": json.dumps(result), "tool_call_id": tool_call.id})
    return results
