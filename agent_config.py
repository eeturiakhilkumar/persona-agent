"""Loads and validates agent.yaml.

.env says WHO the agent represents (name, email, keys, limits).
agent.yaml says WHAT the agent does: its purpose, conversation workflows, UI copy, theme, which
built-in capabilities are on, and which lead-capture forms (tools) it offers.

Validation is strict on purpose: a typo fails at startup with a clear message instead of silently
misbehaving in front of a visitor.
"""
import os
import re
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Placeholders usable inside any text in agent.yaml, e.g. "{user_name}'s background".
PLACEHOLDERS = {"user_name", "user_title", "user_location", "user_email", "agent_name"}

FEATURES = ("knowledge_base", "contact_capture", "scheduling", "escalation")

# Tool names / Firestore collections the app itself uses; lead forms may not reuse them.
BUILTIN_TOOLS = {
    "record_user_details", "record_unknown_question", "query_project_knowledge_base",
    "escalate_to_human", "schedule_google_calendar_meeting",
}
RESERVED_COLLECTIONS = {"general_contacts", "unknown_questions", "scheduled_meetings", "escalations", "chat_sessions"}

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

DEFAULTS = {
    "agent": {
        "name": "persona-agent",
        "tagline": "AI Assistant",
        "badge": "AI ASSISTANT",
        "theme_color": "#d946ef",
        "hero_subtitle": "AI assistant for {user_name}.",
        "greeting": "Hi there! 👋 I'm {agent_name}, the AI assistant for {user_name}.",
    },
    "purpose": "You operate on behalf of {user_name} and help their visitors.",
    "tone": "Professional, articulate, welcoming, and concise.",
    "workflows": [],
    "suggestions": [],
    "features": {name: True for name in FEATURES},
    "lead_forms": [],
}


class ConfigError(ValueError):
    pass


def _unknown_keys(where, data, allowed, errors):
    if not isinstance(data, dict):
        errors.append(f"{where}: expected a mapping, got {type(data).__name__}")
        return False
    for key in data:
        if key not in allowed:
            errors.append(f"{where}: unknown key '{key}' (allowed: {', '.join(sorted(allowed))})")
    return True


def _text(where, value, errors, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        errors.append(f"{where}: must be a non-empty text value")
        return ""
    return value.strip()


def _walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _walk_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_strings(value)


def _validate_form(index, form, seen_names, errors):
    where = f"lead_forms[{index}]"
    allowed = {"name", "description", "collection", "title", "success_message", "fields", "require_any"}
    if not _unknown_keys(where, form, allowed, errors):
        return None
    name = _text(f"{where}.name", form.get("name"), errors)
    if name and not NAME_RE.match(name):
        errors.append(f"{where}.name: '{name}' must be lowercase letters, digits and underscores (start with a letter, 2-40 chars)")
    if name in BUILTIN_TOOLS:
        errors.append(f"{where}.name: '{name}' is a built-in tool name")
    if name in seen_names:
        errors.append(f"{where}.name: '{name}' is defined twice")
    seen_names.add(name)

    collection = _text(f"{where}.collection", form.get("collection"), errors)
    if collection and not NAME_RE.match(collection):
        errors.append(f"{where}.collection: '{collection}' must be lowercase letters, digits and underscores")
    if collection in RESERVED_COLLECTIONS:
        errors.append(f"{where}.collection: '{collection}' is reserved by the app")

    description = _text(f"{where}.description", form.get("description"), errors)
    title = _text(f"{where}.title", form.get("title"), errors, required=False) or name.replace("_", " ").title()
    success = _text(f"{where}.success_message", form.get("success_message"), errors, required=False) or "Details recorded successfully."

    fields = []
    raw_fields = form.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        errors.append(f"{where}.fields: must be a non-empty list")
        raw_fields = []
    field_names = set()
    for j, field in enumerate(raw_fields):
        fwhere = f"{where}.fields[{j}]"
        if not _unknown_keys(fwhere, field, {"name", "description", "choices", "default", "required", "min_chars"}, errors):
            continue
        fname = _text(f"{fwhere}.name", field.get("name"), errors)
        if fname and not NAME_RE.match(fname):
            errors.append(f"{fwhere}.name: '{fname}' must be lowercase letters, digits and underscores")
        if fname in field_names:
            errors.append(f"{fwhere}.name: '{fname}' is defined twice")
        field_names.add(fname)
        choices = field.get("choices")
        if choices is not None:
            if not isinstance(choices, list) or len(choices) < 2 or not all(isinstance(c, str) and c.strip() for c in choices):
                errors.append(f"{fwhere}.choices: must be a list of at least two non-empty texts")
                choices = None
        required = field.get("required", False)
        if not isinstance(required, bool):
            errors.append(f"{fwhere}.required: must be true or false")
            required = False
        min_chars = field.get("min_chars", 0)
        if not isinstance(min_chars, int) or isinstance(min_chars, bool) or min_chars < 0:
            errors.append(f"{fwhere}.min_chars: must be a whole number >= 0")
            min_chars = 0
        default = field.get("default", "not provided")
        if not isinstance(default, str):
            errors.append(f"{fwhere}.default: must be text")
            default = "not provided"
        if choices and not required and default not in choices:
            errors.append(f"{fwhere}.default: '{default}' must be one of the choices {choices}")
        fields.append({
            "name": fname, "description": _text(f"{fwhere}.description", field.get("description"), errors, required=False),
            "choices": choices, "default": default, "required": required, "min_chars": min_chars,
        })

    require_any = form.get("require_any", [])
    if not isinstance(require_any, list) or not all(isinstance(n, str) for n in require_any):
        errors.append(f"{where}.require_any: must be a list of field names")
        require_any = []
    for n in require_any:
        if n not in field_names:
            errors.append(f"{where}.require_any: '{n}' is not a field of this form")

    return {"name": name, "description": description, "collection": collection, "title": title,
            "success_message": success, "fields": fields, "require_any": require_any}


def validate(raw: dict) -> dict:
    """Return the config with defaults applied, or raise ConfigError listing every problem found."""
    errors = []
    if raw is None:
        raw = {}
    if not _unknown_keys("agent.yaml", raw, set(DEFAULTS), errors):
        raise ConfigError("\n - ".join(["Invalid agent config:"] + errors))

    cfg = {key: (dict(value) if isinstance(value, dict) else list(value) if isinstance(value, list) else value)
           for key, value in DEFAULTS.items()}

    # agent
    agent = raw.get("agent", {})
    if _unknown_keys("agent", agent, set(DEFAULTS["agent"]), errors):
        for key, default in DEFAULTS["agent"].items():
            cfg["agent"][key] = _text(f"agent.{key}", agent.get(key, default), errors)
        if not COLOR_RE.match(cfg["agent"]["theme_color"]):
            errors.append("agent.theme_color: must look like #d946ef")

    for key in ("purpose", "tone"):
        cfg[key] = _text(key, raw.get(key, DEFAULTS[key]), errors)

    # workflows
    cfg["workflows"] = []
    workflows = raw.get("workflows", [])
    if not isinstance(workflows, list):
        errors.append("workflows: must be a list")
        workflows = []
    for i, wf in enumerate(workflows):
        where = f"workflows[{i}]"
        if not _unknown_keys(where, wf, {"id", "title", "tag", "blurb", "instructions"}, errors):
            continue
        title = _text(f"{where}.title", wf.get("title"), errors)
        cfg["workflows"].append({
            "id": _text(f"{where}.id", wf.get("id", title.lower().replace(" ", "_")), errors),
            "title": title,
            "tag": (_text(f"{where}.tag", wf.get("tag"), errors, required=False) or title.split()[0]).upper(),
            "blurb": _text(f"{where}.blurb", wf.get("blurb"), errors),
            "instructions": _text(f"{where}.instructions", wf.get("instructions"), errors),
        })

    # suggestions
    suggestions = raw.get("suggestions", [])
    if not isinstance(suggestions, list) or not all(isinstance(s, str) and s.strip() for s in suggestions):
        errors.append("suggestions: must be a list of non-empty texts")
        suggestions = []
    cfg["suggestions"] = [s.strip() for s in suggestions]

    # features
    features = raw.get("features", {})
    if _unknown_keys("features", features, set(FEATURES), errors):
        for name in FEATURES:
            value = features.get(name, True)
            if not isinstance(value, bool):
                errors.append(f"features.{name}: must be true or false")
                value = True
            cfg["features"][name] = value

    # lead forms
    cfg["lead_forms"] = []
    forms = raw.get("lead_forms", [])
    if not isinstance(forms, list):
        errors.append("lead_forms: must be a list")
        forms = []
    seen = set()
    for i, form in enumerate(forms):
        parsed = _validate_form(i, form, seen, errors)
        if parsed:
            cfg["lead_forms"].append(parsed)

    # placeholders in any text must be known
    for text in _walk_strings(raw):
        for ph in re.findall(r"\{(\w+)\}", text):
            if ph not in PLACEHOLDERS:
                errors.append(f"unknown placeholder '{{{ph}}}' (allowed: {', '.join('{' + p + '}' for p in sorted(PLACEHOLDERS))})")

    if errors:
        raise ConfigError("\n - ".join(["Invalid agent config:"] + sorted(set(errors))))
    return cfg


def load_agent_config(path: str = None) -> dict:
    """Load `path` (or $AGENT_CONFIG, or agent.yaml next to this file) and validate it."""
    path = path or os.getenv("AGENT_CONFIG") or os.path.join(BASE_DIR, "agent.yaml")
    candidates = [path, os.path.join(BASE_DIR, path)]
    resolved = next((p for p in candidates if os.path.isfile(p)), None)
    if not resolved:
        raise ConfigError(f"Agent config not found: {path}")
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"{resolved} is not valid YAML: {e}")
    try:
        return validate(raw)
    except ConfigError as e:
        raise ConfigError(f"{e}\n(file: {resolved})")
