"""Telegram human-in-the-loop replies.

One shared poller (guarded by a lock) serves every visitor waiting on an escalation, so concurrent
visitors never steal each other's replies. Only messages from TELEGRAM_CHAT_ID are accepted.
Run a single instance per bot token (e.g. Cloud Run `--max-instances 1`); Telegram allows only one
getUpdates consumer.
"""
import os
import re
import threading
import requests

from tools import set_escalation_status, redact_secrets

UUID_RE = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'

_lock = threading.Lock()
_offset = None
_seeded = False
_waiting = set()      # escalation ids with a visitor waiting right now
_replies = {}         # escalation id -> answer, handed to the waiting visitor


def register_wait(escalation_id: str):
    with _lock:
        _waiting.add(escalation_id)


def finish_wait(escalation_id: str):
    with _lock:
        _waiting.discard(escalation_id)
        _replies.pop(escalation_id, None)


def _is_owner(message: dict) -> bool:
    owner = os.getenv("TELEGRAM_CHAT_ID")
    return bool(owner) and str(message.get("chat", {}).get("id", "")) == str(owner)


def _route(message: dict):
    """Return (escalation_id, answer) for an owner message, or (None, None) if it can't be matched."""
    text = message.get("text", "")
    # 1. Native "swipe to reply" on the bot's escalation message
    if "reply_to_message" in message:
        match = re.search(f'({UUID_RE})', message["reply_to_message"].get("text", ""))
        return (match.group(1), text) if match else (None, None)
    # 2. "<escalation-id> your answer"
    match = re.search(f'^({UUID_RE})\\s+(.+)', text, re.DOTALL)
    if match:
        return match.group(1), match.group(2)
    # 3. A plain message is only unambiguous when exactly one visitor is waiting
    if len(_waiting) == 1:
        return next(iter(_waiting)), text
    return None, None


def poll_for_reply(escalation_id: str):
    """Check Telegram once; return the owner's answer for `escalation_id`, or None."""
    global _offset, _seeded
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return None
    try:
        with _lock:
            if escalation_id in _replies:
                return _replies.pop(escalation_id)

            base = f"https://api.telegram.org/bot{token}/getUpdates"
            if not _seeded:  # skip anything sent before the first escalation
                seed = requests.get(base, params={"timeout": 0, "offset": -1}, timeout=5).json().get("result", [])
                if seed:
                    _offset = seed[-1]["update_id"] + 1
                _seeded = True

            params = {"timeout": 2, "allowed_updates": ["message"]}
            if _offset is not None:
                params["offset"] = _offset
            for update in requests.get(base, params=params, timeout=5).json().get("result", []):
                _offset = update["update_id"] + 1
                message = update.get("message", {})
                if not message.get("text") or not _is_owner(message):
                    continue
                target, answer = _route(message)
                if not (target and answer):
                    continue
                print(f"📥 Caught human reply for escalation {target[:8]}")
                late = target not in _waiting
                set_escalation_status(target, "resolved", reply=answer, **({"late": True} if late else {}))
                if not late:
                    _replies[target] = answer
            return _replies.pop(escalation_id, None)
    except Exception as e:
        print(f"⚠️ Telegram check error: {redact_secrets(e)}")
        return None
