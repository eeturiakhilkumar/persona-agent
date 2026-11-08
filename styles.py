"""Styling constants, CSS, and dynamic HTML partials. All copy comes from .env (who) and agent.yaml (what)."""
import json
from datetime import datetime
from html import escape
from config import (
    AGENT,
    AGENT_NAME,
    USER_NAME,
    USER_TITLE,
    USER_LOCATION,
    USER_CALENDAR_URL,
    USER_LINKEDIN_URL,
    USER_GITHUB_URL,
    PRIVACY_NOTICE,
    USER_SKILLS,
    get_user_initials,
    get_user_summary,
    render,
)

A = AGENT["agent"]
FEATURES = AGENT["features"]

# --- THEME: the stylesheet is written around one accent color; swap it for agent.theme_color ----------
_DEFAULT_ACCENT = {"hex": "#d946ef", "rgb": "217, 70, 239", "light": "#e879f9", "gradient_from": "#f472b6"}

def _mix_with_white(hex_color: str, amount: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(*(round(c + (255 - c) * amount) for c in (r, g, b)))

def _theme(text: str) -> str:
    accent = A["theme_color"].lower()
    r, g, b = (int(accent[i:i + 2], 16) for i in (1, 3, 5))
    return (text.replace(_DEFAULT_ACCENT["rgb"], f"{r}, {g}, {b}")
                .replace(_DEFAULT_ACCENT["hex"], accent)
                .replace(_DEFAULT_ACCENT["light"], _mix_with_white(accent, 0.35))
                .replace(_DEFAULT_ACCENT["gradient_from"], _mix_with_white(accent, 0.5)))

# --- Text (everything inserted into HTML is escaped) ---------------------------------------------------
def _e(text: str) -> str:
    return escape(text)

def _rich(text: str) -> str:
    return _e(render(text)).replace("\n", "<br>")

initials = _e(get_user_initials(USER_NAME))
summary = get_user_summary()
current_year = datetime.now().year
name_e, title_e, location_e, agent_e = _e(USER_NAME), _e(USER_TITLE), _e(USER_LOCATION), _e(AGENT_NAME)
who_e = f"{name_e} ({title_e})" if USER_TITLE else name_e

# Four rotating accents/icons for sidebar cards, welcome bullets and suggestion chips.
_COLORS = ["magenta", "blue", "green", "orange"]
_ICONS = [
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline>',
    '<rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path>',
    '<polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline>',
    '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line>',
]

def _svg(index: int, size: int) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">{_ICONS[index % len(_ICONS)]}</svg>')

# What the agent can do = the workflows from agent.yaml + the built-in capabilities that are switched on.
capabilities = [(wf["title"], wf["tag"], render(wf["blurb"])) for wf in AGENT["workflows"]]
if FEATURES["knowledge_base"]:
    capabilities.append(("Knowledge & Background", "INFO", f"Ask specific questions about {USER_NAME} and get answers from their documents."))
if FEATURES["scheduling"]:
    capabilities.append(("Connect & Schedule", "CONNECT", "Book a meeting or leave contact details for a direct follow-up."))
elif FEATURES["contact_capture"]:
    capabilities.append(("Get in Touch", "CONTACT", "Leave your contact details for a direct follow-up."))

# Render optional social / calendar links
nav_links = []
if USER_CALENDAR_URL:
    nav_links.append(f"""
        <a href="{_e(USER_CALENDAR_URL)}" target="_blank" rel="noopener noreferrer" class="nav-btn-outline" style="text-decoration: none;">
            {_svg(3, 14)}
            Book a Call
        </a>
    """)

if USER_LINKEDIN_URL:
    nav_links.append(f"""
        <a href="{_e(USER_LINKEDIN_URL)}" target="_blank" rel="noopener noreferrer" class="nav-btn-icon" aria-label="LinkedIn">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.85-3.04-1.86 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.47-.9 1.63-1.85 3.36-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.12 2.06 2.06 0 0 1 0 4.12zM7.12 20.45H3.55V9h3.57v11.45z"></path></svg>
        </a>
    """)

if USER_GITHUB_URL:
    nav_links.append(f"""
        <a href="{_e(USER_GITHUB_URL)}" target="_blank" rel="noopener noreferrer" class="nav-btn-icon" aria-label="GitHub">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
        </a>
    """)

nav_links_html = "".join(nav_links)
skills_chips_html = "".join(f"<span>{_e(skill)}</span>" for skill in USER_SKILLS)

chips = []
if USER_TITLE:
    chips.append(f'<div class="highlight-chip"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#d946ef" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg><span>{title_e}</span></div>')
if USER_LOCATION:
    chips.append(f'<div class="highlight-chip"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg><span>{location_e}</span></div>')
nav_chips_html = "".join(chips)

# --- TOP NAVIGATION ---
TOP_NAV_HTML = f"""
<div class="top-nav-bar">
    <div class="nav-left">
        <div class="nav-avatar">{initials}</div>
        <div class="nav-identity">
            <div class="nav-name-row">
                <span class="nav-name">{name_e}</span>
                <span class="badge-pill magenta-badge">{agent_e}</span>
            </div>
            <div class="nav-status-row">
                <span class="online-dot"></span>
                <span class="nav-status">Online • {_e(A['tagline'])}</span>
            </div>
        </div>
    </div>

    <div class="nav-center">
        {nav_chips_html}
    </div>

    <div class="nav-right">
        {nav_links_html}
    </div>
</div>
"""

# --- HERO SECTION ---
HERO_HTML = f"""
<div class="hero-section">
    <div class="hero-pill">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.88 5.76a2 2 0 0 0 1.36 1.36L21 12l-5.76 1.88a2 2 0 0 0-1.36 1.36L12 21l-1.88-5.76a2 2 0 0 0-1.36-1.36L3 12l5.76-1.88a2 2 0 0 0 1.36-1.36L12 3z"></path></svg>
        {_e(A['badge'])}
    </div>
    <h1 class="hero-title">Meet <span class="text-gradient-magenta">{agent_e}</span></h1>
    <p class="hero-subtitle">{_rich(A['hero_subtitle'])}</p>
</div>
"""

# --- LEFT SIDEBAR ---
action_items = "".join(f"""
            <div class="action-item">
                <div class="icon-box {_COLORS[i % 4]}-box">{_svg(i, 18)}</div>
                <div class="action-content">
                    <div class="action-title-row">
                        <h4>{_e(title)}</h4>
                        <span class="tag tag-{_COLORS[i % 4]}">{_e(tag)}</span>
                    </div>
                    <p>{_e(blurb)}</p>
                </div>
            </div>
""" for i, (title, tag, blurb) in enumerate(capabilities))

skills_card = f"""
    <!-- SKILLS -->
    <div class="sidebar-card">
        <div class="card-header">
            <div class="header-left">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>
                <h3>FOCUS AREAS</h3>
            </div>
            <span class="header-action">Topics</span>
        </div>

        <div class="tech-grid">
            {skills_chips_html}
        </div>
    </div>
""" if USER_SKILLS else ""

LEFT_SIDEBAR_HTML = f"""
<div class="sidebar-container">
    <!-- PROFILE CARD -->
    <div class="sidebar-card">
        <div class="card-header">
            <div class="header-left">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#d946ef" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="7" r="4"></circle><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path></svg>
                <h3>ABOUT {_e(USER_NAME.upper())}</h3>
            </div>
            <span class="header-action">Verified</span>
        </div>
        <p class="sidebar-bio">{_e(summary[:280])}...</p>
    </div>

    <!-- HOW I CAN HELP -->
    <div class="sidebar-card">
        <div class="card-header">
            <div class="header-left">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
                <h3>HOW I CAN HELP</h3>
            </div>
            <span class="header-action">Core Capabilities</span>
        </div>

        <div class="action-list">
{action_items}
        </div>
    </div>
{skills_card}
</div>
"""

# --- RIGHT CHAT HEADER ---
CHAT_HEADER_HTML = f"""
<div class="chat-header">
    <div class="chat-header-left">
        <span class="online-dot"></span>
        <span class="chat-title">{_e(AGENT_NAME.upper())} • {_e(USER_NAME.upper())}</span>
    </div>
    <div class="chat-header-right">
        <span class="latency-badge">Online • Ready</span>
    </div>
</div>
"""

# --- INITIAL CHAT WELCOME BUBBLE ---
welcome_items = "".join(f"""
                <li><span class="mini-icon {_COLORS[i % 4]}-mini">{_svg(i, 14)}</span> <span><strong>{_e(title)}:</strong> {_e(blurb)}</span></li>""" for i, (title, _tag, blurb) in enumerate(capabilities))
welcome_list = f"""<p><strong>Here is how I can assist you today:</strong></p>
            <ul class="welcome-list">{welcome_items}
            </ul>""" if capabilities else ""
pills = "".join(f'\n        <button class="s-pill {_COLORS[i % 4]}-pill">{_svg(i, 14)} {_e(text)}</button>' for i, text in enumerate(AGENT["suggestions"]))
pills_html = f'\n    <div class="suggestion-pills">{pills}\n    </div>' if pills else ""

INITIAL_CHAT_HTML = f"""
<div class="welcome-chat-container">
    <div class="chat-bubble bot-bubble">
        <div class="bot-avatar">{initials}</div>
        <div class="bubble-content">
            <p>{_e(render(A['greeting']))}</p>
            <p><strong>About {name_e}:</strong> {_e(summary)}</p>
            {welcome_list}
            <p>What would you like to discuss?</p>
        </div>
    </div>
{pills_html}
</div>
"""

# --- FOOTER ---
FOOTER_HTML = f"""
<div class="page-footer">
    <div class="footer-left">© {current_year} {name_e} • Powered by {agent_e}</div>
    <div class="footer-right">
        <span>{_e(A['tagline'])}</span>
    </div>
</div>
<p class="privacy-note">{_e(PRIVACY_NOTICE)}</p>
"""

CSS = """
/* GLOBAL RESETS */
html, body, gradio-app {
    background-color: #0b1121 !important;
    color: #f8fafc !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    margin: 0; padding: 0;
    min-height: 100vh !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    box-sizing: border-box !important;
}
.gradio-container { max-width: 1360px !important; margin: 0 auto !important; padding: 0 20px !important; min-height: 100vh !important; display: flex !important; flex-direction: column !important; box-sizing: border-box !important; }
.gradio-container > .main, .gradio-container > .main > .wrap { display: flex !important; flex-direction: column !important; }
footer, .built-with { display: none !important; }
* { box-sizing: border-box; }
.block, .form, .wrap, .main { min-width: 0 !important; }

/* GRADIO DARK THEME MAPPINGS */
:root, .dark, body.dark, .gradio-container {
    --body-text-color: #f8fafc !important;
    --body-text-color-subdued: #cbd5e1 !important;
    --background-fill-primary: #0b1121 !important;
    --background-fill-secondary: #111827 !important;
    --block-background-fill: #111827 !important;
    --block-border-color: #1f2937 !important;
    --border-color-primary: #1f2937 !important;
    --input-background-fill: #0b1121 !important;
    --input-text-color: #f8fafc !important;
    --input-placeholder-color: #64748b !important;
    --button-primary-background-fill: #d946ef !important;
    --button-primary-text-color: #ffffff !important;
    --button-secondary-background-fill: #1f2937 !important;
    --button-secondary-text-color: #f8fafc !important;
    --chatbot-text-color: #f8fafc !important;
    --link-text-color: #38bdf8 !important;
}

/* HIGH-CONTRAST TEXT FOR GENERAL UI */
.gradio-container .prose, .gradio-container .prose p, .gradio-container .prose li,
.gradio-container .prose span, .output-markdown, .output-markdown p, .output-markdown li,
.gr-box label, .block-label, label span {
    color: #e2e8f0 !important;
}
.gradio-container h1, .gradio-container h2, .gradio-container h3,
.chatbot .prose strong, .gradio-container .prose strong { color: #f8fafc !important; }
.chatbot .prose a, .gradio-container .prose a, .bubble-content a { color: #38bdf8 !important; }

/* USER CHAT BUBBLE & FONT COLOR (Dark text on light bubble for maximum contrast) */
.chatbot .message.user,
.chatbot [data-testid="user"],
.chatbot .user,
.chatbot .user-row,
.message-row.user-row,
div[data-testid="user"],
.message.user {
    background-color: #f8fafc !important;
    color: #0f172a !important;
    border-radius: 14px !important;
}

.chatbot .message.user *,
.chatbot [data-testid="user"] *,
.chatbot .user *,
.chatbot .user-row *,
.message-row.user-row *,
div[data-testid="user"] *,
.message.user *,
.user-row p,
.message.user p {
    color: #0f172a !important;
    -webkit-text-fill-color: #0f172a !important;
    font-weight: 500 !important;
}

/* BOT CHAT BUBBLE & FONT COLOR (Bright text on dark navy) */
.chatbot .message.bot,
.chatbot [data-testid="bot"],
.chatbot .bot,
.chatbot .bot-row,
.message-row.bot-row,
div[data-testid="bot"],
.message.bot {
    background-color: #111827 !important;
    color: #f8fafc !important;
}

.chatbot .message.bot *,
.chatbot [data-testid="bot"] *,
.chatbot .bot *,
.chatbot .bot-row *,
.message-row.bot-row *,
div[data-testid="bot"] *,
.message.bot * {
    color: #e2e8f0 !important;
    -webkit-text-fill-color: #e2e8f0 !important;
}

/* CHAT INPUT FIELD */
.form, form, [data-testid="textbox"], .textbox, .gr-textbox, .input-container {
    background: #0b1121 !important;
    border-color: rgba(255,255,255,0.12) !important;
}
textarea, input[type="text"], [data-testid="textbox"] textarea, .gr-textbox textarea {
    background: #0b1121 !important;
    color: #f8fafc !important;
    -webkit-text-fill-color: #f8fafc !important;
}
textarea::placeholder, input::placeholder { color: #64748b !important; -webkit-text-fill-color: #64748b !important; }

/* ACCENTS & ICONS */
.icon-box, .mini-icon { border-width: 1px; border-style: solid; }
.icon-box svg, .mini-icon svg { stroke: currentColor !important; }
.blue-box, .blue-mini { color: #60a5fa !important; background: rgba(59, 130, 246, 0.15); border-color: rgba(59, 130, 246, 0.3); }
.magenta-box, .magenta-mini { color: #e879f9 !important; background: rgba(217, 70, 239, 0.15); border-color: rgba(217, 70, 239, 0.3); }
.green-box, .green-mini { color: #34d399 !important; background: rgba(16, 185, 129, 0.15); border-color: rgba(16, 185, 129, 0.3); }
.orange-box, .orange-mini { color: #fbbf24 !important; background: rgba(245, 158, 11, 0.15); border-color: rgba(245, 158, 11, 0.3); }

/* TOP NAV */
.top-nav-bar { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.06); margin-bottom: 16px; }
.nav-left, .nav-center, .nav-right { display: flex; align-items: center; gap: 12px; }
.nav-avatar { width: 40px; height: 40px; background: #8b5cf6; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-weight: bold; }
.nav-identity { display: flex; flex-direction: column; }
.nav-name-row { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.magenta-badge { background: rgba(217, 70, 239, 0.15); color: #d946ef; font-size: 11px; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(217, 70, 239, 0.3); font-weight: 600; }
.nav-status-row { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #94a3b8; }
.online-dot { width: 8px; height: 8px; background: #22c55e; border-radius: 50%; display: inline-block; }
.highlight-chip { display: flex; align-items: center; gap: 6px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); padding: 6px 14px; border-radius: 20px; font-size: 12.5px; color: #cbd5e1; }
.nav-btn-outline { display: flex; align-items: center; gap: 6px; background: transparent; border: 1px solid rgba(217, 70, 239, 0.5); color: #e879f9; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-weight: 500; font-size: 13px; }
.nav-btn-icon { width: 36px; height: 36px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #cbd5e1; text-decoration: none; }
.nav-btn-icon:hover { background: rgba(255,255,255,0.1); color: #fff; }

/* HERO */
.hero-section { text-align: center; margin-bottom: 16px; }
.hero-pill { display: inline-flex; align-items: center; gap: 6px; border: 1px solid rgba(217, 70, 239, 0.4); color: #e879f9; background: rgba(217, 70, 239, 0.1); padding: 4px 14px; border-radius: 20px; font-size: 11px; font-weight: 600; letter-spacing: 1px; margin-bottom: 8px; }
.hero-title { font-size: 32px; font-weight: 700; margin: 0 0 6px 0; line-height: 1.15; }
.text-gradient-magenta { background: linear-gradient(90deg, #f472b6, #d946ef); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.hero-subtitle { color: #94a3b8; font-size: 14px; line-height: 1.5; margin: 0; }

/* DASHBOARD GRID */
.dashboard-grid { display: flex !important; flex-wrap: nowrap !important; gap: 16px !important; margin-bottom: 12px; align-items: flex-start !important; }
.dashboard-grid > .left-col, .dashboard-grid > .right-col { min-width: 0 !important; max-width: 100% !important; }

/* SIDEBAR */
.sidebar-container { display: flex; flex-direction: column; gap: 12px; }
.sidebar-card { background: #111827; border: 1px solid #1f2937; border-radius: 14px; padding: 14px; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 10px; }
.header-left { display: flex; align-items: center; gap: 8px; }
.header-left h3 { margin: 0; font-size: 12px; letter-spacing: 1px; color: #f8fafc; font-weight: 600; }
.header-action { color: #94a3b8; font-size: 12px; }
.sidebar-bio { font-size: 12.5px; color: #94a3b8; line-height: 1.5; margin: 0; }

.action-list { display: flex; flex-direction: column; gap: 8px; }
.action-item { display: flex; align-items: center; gap: 10px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); padding: 10px 12px; border-radius: 10px; }
.icon-box { width: 38px; height: 38px; border-radius: 10px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.action-content { flex-grow: 1; min-width: 0; }
.action-title-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 3px; }
.action-title-row h4 { margin: 0; font-size: 13px; color: #f8fafc; font-weight: 600; }
.tag { font-size: 9px; padding: 2px 6px; border-radius: 4px; font-weight: bold; border: 1px solid; flex-shrink: 0; }
.tag-blue { color: #60a5fa; border-color: rgba(59, 130, 246, 0.3); background: rgba(59, 130, 246, 0.1); }
.tag-magenta { color: #e879f9; border-color: rgba(217, 70, 239, 0.3); background: rgba(217, 70, 239, 0.1); }
.tag-green { color: #34d399; border-color: rgba(16, 185, 129, 0.3); background: rgba(16, 185, 129, 0.1); }
.tag-orange { color: #fbbf24; border-color: rgba(245, 158, 11, 0.3); background: rgba(245, 158, 11, 0.1); }
.action-content p { margin: 0; font-size: 12px; color: #94a3b8; line-height: 1.4; }

.tech-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.tech-grid span { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); padding: 4px 10px; border-radius: 16px; font-size: 11.5px; color: #cbd5e1; }

/* RIGHT CHAT AREA */
.right-col { background: #111827; border: 1px solid #1f2937; border-radius: 14px; display: flex; flex-direction: column; overflow: hidden; }
.chat-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.chat-header-left { display: flex; align-items: center; gap: 8px; }
.chat-title { font-weight: bold; letter-spacing: 1px; font-size: 12px; }
.chat-header-right { display: flex; align-items: center; gap: 12px; }
.latency-badge { color: #34d399; font-size: 12px; background: rgba(16, 185, 129, 0.1); padding: 2px 8px; border-radius: 12px; border: 1px solid rgba(16, 185, 129, 0.3); }

.chat-wrapper { padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.welcome-chat-container { display: flex; flex-direction: column; gap: 10px; margin-bottom: 8px; }
.chat-bubble { display: flex; gap: 12px; }
.bot-avatar { width: 32px; height: 32px; background: #8b5cf6; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 12px; flex-shrink: 0; }
.bubble-content { color: #e2e8f0; font-size: 13px; line-height: 1.5; }
.bubble-content p { margin: 0 0 8px 0; }
.welcome-list { list-style: none; padding: 0; margin: 0 0 10px 0; }
.welcome-list li { margin-bottom: 8px; display: flex; gap: 8px; align-items: flex-start; }
.mini-icon { width: 24px; height: 24px; border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }

/* Suggestion Pills */
.suggestion-pills { display: flex; gap: 8px; flex-wrap: wrap; margin-left: 44px; }
.s-pill { display: flex; align-items: center; gap: 6px; background: transparent; border: 1px solid; padding: 6px 14px; border-radius: 20px; color: #fff; cursor: pointer; font-size: 12px; }
.blue-pill { border-color: rgba(59, 130, 246, 0.5); }
.magenta-pill { border-color: rgba(217, 70, 239, 0.5); }
.green-pill { border-color: rgba(16, 185, 129, 0.5); }
.orange-pill { border-color: rgba(245, 158, 11, 0.5); }

/* Gradio Input Area Overrides */
.form { border: 1px solid rgba(255,255,255,0.1) !important; background: #0b1121 !important; border-radius: 12px !important; }
.form:focus-within { border-color: #d946ef !important; }
button.submit { background: #d946ef !important; border-radius: 8px !important; margin: 6px !important; }

/* FOOTER */
.page-footer { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-top: 1px solid rgba(255,255,255,0.06); color: #94a3b8; font-size: 12px; margin-top: auto; }
.page-footer a { color: #cbd5e1; text-decoration: none; }
.privacy-note { color: #64748b; font-size: 11px; text-align: center; margin: 4px 0 12px; }
"""

JS = """
() => {
  document.title = __AGENT_TITLE__;

  setTimeout(() => {
    const areas = document.querySelectorAll('textarea');
    if (areas.length) areas[areas.length - 1].focus();
  }, 300);

  setInterval(() => {
    const textareas = document.querySelectorAll('textarea');
    if (!textareas.length) return;
    
    const area = textareas[textareas.length - 1];
    const form = area.closest('.form, form') || area.parentElement.parentElement;
    if (!form) return;
    
    const btn = form.querySelector('button.primary, button.submit, button[aria-label*="Send"], button[aria-label*="Submit"], button');
    if (!btn) return;
    
    const isEmpty = area.value.trim().length === 0;
    btn.disabled = isEmpty;

    const bubbles = document.querySelectorAll('.chatbot .prose');
    let hasChat = false;
    bubbles.forEach(b => {
        if (b.textContent.trim().length > 0) hasChat = true;
    });

    const intro = document.querySelector('.initial-state-container');
    if (intro) {
        if (hasChat) {
            intro.style.setProperty('display', 'none', 'important');
        } else {
            intro.style.setProperty('display', 'block', 'important');
        }
    }
  }, 100);
}
"""

# Apply the accent color to the stylesheet and to the inline-colored HTML, and the agent name to the page title.
CSS = _theme(CSS)
JS = JS.replace("__AGENT_TITLE__", json.dumps(AGENT_NAME))
TOP_NAV_HTML, HERO_HTML, LEFT_SIDEBAR_HTML, CHAT_HEADER_HTML, INITIAL_CHAT_HTML, FOOTER_HTML = (
    _theme(h) for h in (TOP_NAV_HTML, HERO_HTML, LEFT_SIDEBAR_HTML, CHAT_HEADER_HTML, INITIAL_CHAT_HTML, FOOTER_HTML)
)
