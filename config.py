import os
from dotenv import load_dotenv

# Single place where .env is loaded; every other module imports config first.
load_dotenv()  # real environment variables (e.g. on Cloud Run) take precedence over .env

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Core Agent Configuration
AGENT_NAME = "persona-agent"

# Knowledge base (shared by ingest.py and tools.py)
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")
COLLECTION_NAME = "project_knowledge"
EMBED_MODEL = "text-embedding-3-small"
SUMMARY_PATH = os.path.join(KNOWLEDGE_DIR, "summary.txt")

# User Profile Configuration (set via environment variables or .env)
USER_NAME = os.getenv("USER_NAME", "Alex Morgan")
USER_TITLE = os.getenv("USER_TITLE", "Senior Software Engineer")
USER_LOCATION = os.getenv("USER_LOCATION", "Remote / Global")
USER_EMAIL = os.getenv("USER_EMAIL", "alex.morgan@example.com")
USER_CALENDAR_URL = os.getenv("USER_CALENDAR_URL", "")
USER_LINKEDIN_URL = os.getenv("USER_LINKEDIN_URL", "")
USER_GITHUB_URL = os.getenv("USER_GITHUB_URL", "")

USER_SKILLS = [
    s.strip()
    for s in os.getenv(
        "USER_SKILLS",
        "Full-Stack Development, System Architecture, Python, TypeScript, React, Cloud & DevOps, AI Agents",
    ).split(",")
    if s.strip()
]

# Shown to the model whenever it should point a visitor at another way to reach the user.
BOOKING_HINT = (
    f"Offer self-service booking at {USER_CALENDAR_URL} instead."
    if USER_CALENDAR_URL
    else f"Suggest reaching out via email at {USER_EMAIL}."
)

def get_user_initials(name: str = USER_NAME) -> str:
    """Extract up to 2 uppercase initials from a name."""
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if len(parts) == 1 and parts[0]:
        return parts[0][:2].upper()
    return "PA"

def get_user_summary() -> str:
    """Load knowledge/summary.txt, falling back to a generic sentence."""
    try:
        with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            return content
    except OSError:
        pass
    return f"{USER_NAME} is an experienced {USER_TITLE}."
