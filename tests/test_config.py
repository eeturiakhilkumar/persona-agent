"""agent.yaml validation, required profile, and that other use cases really change the agent.
Run: python tests/test_config.py"""
import json, os, subprocess, sys, tempfile, textwrap

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import agent_config
from agent_config import ConfigError, load_agent_config, validate


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def rejects(raw, expected_fragment):
    try:
        validate(raw)
    except ConfigError as e:
        return expected_fragment in str(e)
    return False


# ---- shipped configs are valid -------------------------------------------------------------------
for path in ("agent.yaml", "examples/support-bot.yaml", "examples/sales-assistant.yaml"):
    check(f"{path} is valid", load_agent_config(path)["agent"]["name"])

form = {"name": "open_ticket", "description": "d", "collection": "tickets", "fields": [{"name": "issue"}]}

# ---- validation catches mistakes with clear messages ---------------------------------------------
check("unknown top-level key", rejects({"workflow": []}, "unknown key 'workflow'"))
check("unknown agent key", rejects({"agent": {"nmae": "x"}}, "unknown key 'nmae'"))
check("bad theme color", rejects({"agent": {"theme_color": "red"}}, "theme_color"))
check("unknown placeholder", rejects({"purpose": "Help {customer}"}, "unknown placeholder '{customer}'"))
check("tool name clash with built-in", rejects({"lead_forms": [dict(form, name="escalate_to_human")]}, "built-in tool name"))
check("duplicate tool name", rejects({"lead_forms": [form, form]}, "defined twice"))
check("reserved collection", rejects({"lead_forms": [dict(form, collection="escalations")]}, "reserved"))
check("invalid tool name", rejects({"lead_forms": [dict(form, name="Open Ticket")]}, "lowercase"))
check("require_any must name a field", rejects({"lead_forms": [dict(form, require_any=["nope"])]}, "not a field"))
check("choice default must be a choice", rejects({"lead_forms": [dict(form, fields=[{"name": "sev", "choices": ["a", "b"], "default": "c"}])]}, "must be one of the choices"))
check("form needs fields", rejects({"lead_forms": [dict(form, fields=[])]}, "non-empty list"))
check("feature flags must be booleans", rejects({"features": {"scheduling": "yes"}}, "true or false"))
check("workflow needs instructions", rejects({"workflows": [{"title": "t", "blurb": "b"}]}, "instructions"))
try:
    validate({"agent": {"theme_color": "red"}, "purpose": "{x}"})
except ConfigError as err:
    check("several errors reported at once", "theme_color" in str(err) and "unknown placeholder" in str(err))
check("empty file gives working defaults", validate(None)["features"]["scheduling"] is True)

with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
    f.write("agent: [unclosed")
try:
    load_agent_config(f.name)
    check("broken YAML is reported", False)
except ConfigError as e:
    check("broken YAML is reported", "not valid YAML" in str(e))
try:
    load_agent_config("does-not-exist.yaml")
    check("missing file is reported", False)
except ConfigError as e:
    check("missing file is reported", "not found" in str(e))


# ---- the app really changes with the config (fresh interpreter per config) ------------------------
def probe(config_path, user_name="Acme Support", extra_env=None):
    code = textwrap.dedent("""
        import json, os
        os.environ["OPENAI_API_KEY"] = ""
        import config, context, styles, tools
        print(json.dumps({
            "agent_name": config.AGENT_NAME,
            "tools": [t["function"]["name"] for t in tools.tools],
            "prompt": context.TWIN_SYSTEM_PROMPT,
            "html": styles.TOP_NAV_HTML + styles.HERO_HTML + styles.LEFT_SIDEBAR_HTML + styles.INITIAL_CHAT_HTML + styles.FOOTER_HTML,
            "css": styles.CSS, "js": styles.JS,
        }))
    """)
    env = dict(os.environ, USER_NAME=user_name, AGENT_CONFIG=config_path, USER_TITLE="", USER_LOCATION="", USER_EMAIL="",
               USER_SKILLS="", USER_CALENDAR_URL="")
    env.update(extra_env or {})
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr[-1500:])
    return json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 else None

support = probe("examples/support-bot.yaml")
check("support bot starts", support is not None)
check("support bot has its own name and tools", support["agent_name"] == "help-desk" and "create_support_ticket" in support["tools"])
check("support bot has no recruiter/project tools", not any(t in support["tools"] for t in ("log_recruiter_opportunity", "capture_project_scope")))
check("scheduling+escalation off -> tools absent", not any(t in support["tools"] for t in ("schedule_google_calendar_meeting", "escalate_to_human")))
check("prompt is about support, not recruiting", "support" in support["prompt"].lower() and "recruiter" not in support["prompt"].lower())
check("prompt does not mention disabled tools", "schedule_google_calendar_meeting" not in support["prompt"] and "escalate_to_human" not in support["prompt"])
check("UI uses the support copy and theme", "Troubleshooting" in support["html"] and "Recruiter" not in support["html"] and "#38bdf8" in support["css"] and "#d946ef" not in support["css"])
check("page title is the agent name", '"help-desk"' in support["js"])
check("empty title/location/skills leave no empty placeholders", "()" not in support["prompt"] and "()" not in support["html"] and "FOCUS AREAS" not in support["html"])

default = probe("agent.yaml", user_name="Jane Doe", extra_env={"USER_TITLE": "Data Scientist"})
check("default config = personal representative", default["agent_name"] == "persona-agent" and
      {"log_recruiter_opportunity", "capture_project_scope", "schedule_google_calendar_meeting", "escalate_to_human"} <= set(default["tools"]))
check("default prompt keeps recruiter/project workflows", "Recruiter Inquiries".upper() in default["prompt"] and "Projects & Consulting".upper() in default["prompt"])
check("profile values are rendered and escaped", "Jane Doe (Data Scientist)" in default["prompt"] and "{user_name}" not in default["prompt"] + default["html"])

none_on = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
none_on.write("features: {knowledge_base: false, contact_capture: false, scheduling: false, escalation: false}\n"); none_on.close()
bare = probe(none_on.name)
check("everything off -> no tools, still starts", bare is not None and bare["tools"] == [])

# ---- required profile ----------------------------------------------------------------------------
out = subprocess.run([sys.executable, "-c", "import config"], cwd=ROOT, env=dict(os.environ, USER_NAME=""), capture_output=True, text=True)
check("missing USER_NAME stops startup with a clear message", out.returncode != 0 and "USER_NAME is not set" in out.stderr)
bad = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False); bad.write("agent: {theme_color: nope}\n"); bad.close()
out = subprocess.run([sys.executable, "-c", "import config"], cwd=ROOT, env=dict(os.environ, USER_NAME="X", AGENT_CONFIG=bad.name), capture_output=True, text=True)
check("invalid agent.yaml stops startup naming the file", out.returncode != 0 and "theme_color" in out.stderr and bad.name in out.stderr)

print("ALL PASSED")
