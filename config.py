import os
import re
import sys
import threading
from dotenv import load_dotenv

from agent_config import ConfigError, load_agent_config

# Single place where .env is loaded; every other module imports config first.
load_dotenv()  # real environment variables (e.g. on Cloud Run) take precedence over .env

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _fail(message: str):
    sys.exit(f"\n❌ {message}\n")

# --- WHAT the agent does: agent.yaml (or the file named by AGENT_CONFIG) ---------------------------
try:
    AGENT = load_agent_config()
except ConfigError as e:
    _fail(str(e))

AGENT_NAME = AGENT["agent"]["name"]

# --- WHO it represents: .env ------------------------------------------------------------------------
USER_NAME = (os.getenv("USER_NAME") or "").strip()
if not USER_NAME:
    _fail("USER_NAME is not set. Copy .env.example to .env and set USER_NAME to the person or business "
          "this agent speaks for (and OPENAI_API_KEY).")
USER_TITLE = (os.getenv("USER_TITLE") or "").strip()
USER_LOCATION = (os.getenv("USER_LOCATION") or "").strip()
USER_EMAIL = (os.getenv("USER_EMAIL") or "").strip()
USER_CALENDAR_URL = (os.getenv("USER_CALENDAR_URL") or "").strip()
USER_LINKEDIN_URL = (os.getenv("USER_LINKEDIN_URL") or "").strip()
USER_GITHUB_URL = (os.getenv("USER_GITHUB_URL") or "").strip()
USER_SKILLS = [s.strip() for s in (os.getenv("USER_SKILLS") or "").split(",") if s.strip()]

def render(text: str) -> str:
    """Fill {user_name} etc. in text from agent.yaml, and drop the empty '()' left by a missing title."""
    values = {
        "user_name": USER_NAME, "user_title": USER_TITLE, "user_location": USER_LOCATION,
        "user_email": USER_EMAIL, "agent_name": AGENT_NAME,
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return re.sub(r"[ \t]*\([ \t]*\)", "", text)

# Knowledge base (shared by ingest.py and tools.py)
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")
COLLECTION_NAME = "project_knowledge"
EMBED_MODEL = "text-embedding-3-small"
SUMMARY_PATH = os.path.join(KNOWLEDGE_DIR, "summary.txt")

# Set while the knowledge index is being (re)built, so searches can say "not ready yet" instead of failing.
INGEST_RUNNING = threading.Event()

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default

# Abuse / cost guards (all overridable via .env)
MAX_MESSAGE_CHARS = _env_int("MAX_MESSAGE_CHARS", 2000)          # longest single visitor message
MAX_HISTORY_MESSAGES = _env_int("MAX_HISTORY_MESSAGES", 20)      # past messages sent to the model
CHAT_MESSAGES_PER_SESSION = _env_int("CHAT_MESSAGES_PER_SESSION", 30)   # per 10 minutes
CHAT_MESSAGES_PER_IP = _env_int("CHAT_MESSAGES_PER_IP", 60)             # per 10 minutes

# Meeting rules for the calendar tool
MEETING_START_HOUR = _env_int("MEETING_START_HOUR", 9)           # earliest start, in MEETING_DEFAULT_TIMEZONE
MEETING_END_HOUR = _env_int("MEETING_END_HOUR", 18)              # latest end
MEETING_MAX_MINUTES = _env_int("MEETING_MAX_MINUTES", 60)
MEETING_MAX_DAYS_AHEAD = _env_int("MEETING_MAX_DAYS_AHEAD", 60)
MEETING_WORKDAYS_ONLY = os.getenv("MEETING_WORKDAYS_ONLY", "true").lower() != "false"

PRIVACY_NOTICE = os.getenv(
    "PRIVACY_NOTICE",
    f"This chat is run by an AI assistant. Messages may be stored, shared with {USER_NAME} and processed by OpenAI. "
    "Please don't share sensitive personal information.",
)

# Shown to the model whenever it should point a visitor at another way to reach the user.
if USER_CALENDAR_URL:
    BOOKING_HINT = f"Offer self-service booking at {USER_CALENDAR_URL} instead."
elif USER_EMAIL:
    BOOKING_HINT = f"Suggest reaching out via email at {USER_EMAIL}."
else:
    BOOKING_HINT = f"Apologize that no other contact method is available right now and invite them to try again later."

def get_user_initials(name: str = USER_NAME) -> str:
    """Extract up to 2 uppercase initials from a name."""
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if len(parts) == 1 and parts[0]:
        return parts[0][:2].upper()
    return "AI"

def get_user_summary() -> str:
    """Load knowledge/summary.txt, falling back to a short generic sentence."""
    try:
        with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            return content
    except OSError:
        pass
    return f"{USER_NAME}{' - ' + USER_TITLE if USER_TITLE else ''}. No profile summary has been provided yet."
