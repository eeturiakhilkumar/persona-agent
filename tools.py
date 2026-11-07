import json
import os
import requests
import re
import uuid
import functools
from html import escape
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import firebase_admin
from firebase_admin import credentials, firestore
from pydantic import BaseModel
from typing import Literal

from config import (
    AGENT_NAME,
    BASE_DIR,
    BOOKING_HINT,
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBED_MODEL,
    USER_NAME,
    USER_EMAIL,
    USER_CALENDAR_URL,
)

pushover_user = os.getenv("PUSHOVER_USER")
pushover_token = os.getenv("PUSHOVER_TOKEN")
pushover_url = "https://api.pushover.net/1/messages.json"

def push(message: str, title: str = f"{AGENT_NAME} Alert"):
    if not pushover_token or not pushover_user:
        return
    try:
        requests.post(pushover_url, data={
            "token": pushover_token,
            "user": pushover_user,
            "message": message,
            "title": title,
            "html": 1
        }, timeout=10)
    except Exception as e:
        print(f"Push notification failed: {e}")

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

def notify_and_store(collection_name: str, payload: dict, push_title: str, push_html_message: str):
    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    payload["status"] = "new"
    
    if db is not None:
        try:
            db.collection(collection_name).add(payload)
        except Exception as e:
            print(f"❌ Firestore Error: {str(e)}")
    else:
        print(f"📝 [Local Log - {collection_name}] {json.dumps(payload)}")

    push(push_html_message, title=push_title)

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
    payload = {"email": email, "name": name, "notes": notes}
    title = f"✉️ Contact Request for {USER_NAME}"
    msg = f"<b>Name:</b> {escape(name)}<br><b>Email:</b> {escape(email)}<br><b>Notes:</b> {escape(notes)}"
    notify_and_store("general_contacts", payload, title, msg)
    return "Contact details recorded successfully."

def record_unknown_question(question: str):
    payload = {"question": question}
    title = f"❓ Unknown Question for {USER_NAME}"
    msg = f"<b>Question:</b> {escape(question)}"
    notify_and_store("unknown_questions", payload, title, msg)
    return "Question logged for review."

def log_recruiter_opportunity(company: str = "not provided", tech_stack: str = "not provided", compensation: str = "not provided", work_model: str = "Unknown", notes: str = "not provided"):
    payload = {"company": company, "tech_stack": tech_stack, "compensation": compensation, "work_model": work_model, "notes": notes}
    title = f"💼 Recruiter Lead for {USER_NAME}"
    msg = f"<b>Company:</b> {escape(company)}<br><b>Stack:</b> {escape(tech_stack)}<br><b>Comp:</b> {escape(compensation)}<br><b>Model:</b> {escape(work_model)}<br><b>Notes:</b> {escape(notes)}"
    notify_and_store("recruiter_leads", payload, title, msg)
    return "Opportunity logged successfully."

def capture_project_scope(problem_statement: str, budget: str = "not provided", timeline: str = "not provided"):
    payload = {"problem_statement": problem_statement, "budget": budget, "timeline": timeline}
    title = f"🚀 New Project Scope for {USER_NAME}"
    msg = f"<b>Problem:</b> {escape(problem_statement)}<br><b>Budget:</b> {escape(budget)}<br><b>Timeline:</b> {escape(timeline)}"
    notify_and_store("project_leads", payload, title, msg)
    return "Project scope captured successfully."

@functools.lru_cache(maxsize=1)
def _get_collection():
    """Open the Chroma collection once; only called after the index exists, so a later `ingest.py` still works."""
    import chromadb
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    embedding_function = OpenAIEmbeddingFunction(api_key=os.environ.get("OPENAI_API_KEY"), model_name=EMBED_MODEL)
    return client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=embedding_function)

def query_project_knowledge_base(query: str):
    if not os.path.exists(CHROMA_PATH):
        return "Knowledge base has not been initialized. No indexed documents found."
    try:
        results = _get_collection().query(query_texts=[query], n_results=3)
        if not results["documents"] or not results["documents"][0]:
            return "No relevant context found in the knowledge base."
        return "\n\n---\n\n".join(results["documents"][0])
    except Exception as e:
        return f"Knowledge retrieval unavailable: {str(e)}"

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
            print(f"❌ Telegram Error: {str(e)}")

    if not telegram_confirmed:
        if db is not None:
            try:
                db.collection("escalations").document(escalation_id).update({"status": "notification_failed"})
            except Exception:
                pass
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
        
    if not attendee_email or "@" not in attendee_email:
        return "A valid attendee email address is required before scheduling. Please ask the visitor for their email."
        
    end_dt = start_dt + timedelta(minutes=duration_minutes or 30)

    try:
        service = get_calendar_service()
    except Exception as e:
        return f"Automated calendar booking is currently not configured ({str(e)[:120]}). {booking_fallback}"

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
            f"({duration_minutes or 30} min). Google Meet Link: {meet_link}. "
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

class LogRecruiterOpportunity(BaseModel):
    """Log details from a recruiter or hiring manager regarding a job opportunity. Call as soon as core facts exist."""
    company: str = "not provided"
    tech_stack: str = "not provided"
    compensation: str = "not provided"
    work_model: Literal["Remote", "Hybrid", "On-site", "Unknown"] = "Unknown"
    notes: str = "not provided"

class CaptureProjectScope(BaseModel):
    """Log details for a potential client project, freelance inquiry, or technical collaboration. Call as soon as the problem statement is provided."""
    problem_statement: str
    budget: str = "not provided"
    timeline: str = "not provided"

class QueryProjectKnowledgeBase(BaseModel):
    """Search the vector database for contextual information about the user's projects, background, and experience."""
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

def pydantic_to_openai_schema(model_class: type[BaseModel]) -> dict:
    schema = model_class.model_json_schema()
    name = _to_snake_case(model_class.__name__)
    parameters = {"type": "object", "properties": schema.get("properties", {}), "additionalProperties": False}
    if "required" in schema: parameters["required"] = schema["required"]
    return {"type": "function", "function": {"name": name, "description": schema.get("description", ""), "parameters": parameters}}

tools = [
    pydantic_to_openai_schema(RecordUserDetails),
    pydantic_to_openai_schema(RecordUnknownQuestion),
    pydantic_to_openai_schema(LogRecruiterOpportunity),
    pydantic_to_openai_schema(CaptureProjectScope),
    pydantic_to_openai_schema(QueryProjectKnowledgeBase),
    pydantic_to_openai_schema(EscalateToHuman),
    pydantic_to_openai_schema(ScheduleGoogleCalendarMeeting)
]

tool_map = {
    "record_user_details": record_user_details,
    "record_unknown_question": record_unknown_question,
    "log_recruiter_opportunity": log_recruiter_opportunity,
    "capture_project_scope": capture_project_scope,
    "query_project_knowledge_base": query_project_knowledge_base,
    "escalate_to_human": escalate_to_human,
    "schedule_google_calendar_meeting": schedule_google_calendar_meeting
}

def handle_tool_calls(tool_calls):
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
