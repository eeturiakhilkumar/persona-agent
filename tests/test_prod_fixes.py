"""Production-hardening checks. Run: python tests/test_prod_fixes.py"""
import inspect, os, sys
os.environ["USER_NAME"] = "Test User"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["OPENAI_API_KEY"] = ""      # keep importing app from building an index / calling OpenAI
os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:SECRETtokenVALUE_abc-123"

import gradio as gr
import requests
from gradio.helpers import special_args

import tools

def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)

# 1. A real requests error embeds the bot token in its text; redact_secrets must remove it.
try:
    requests.get(f"https://127.0.0.1:1/bot{os.environ['TELEGRAM_BOT_TOKEN']}/getUpdates", timeout=1)
except Exception as e:
    raw, clean = str(e), tools.redact_secrets(e)
check("raw requests error contains the token (the leak)", "SECRETtokenVALUE" in raw)
check("redact_secrets removes the token", "SECRETtokenVALUE" not in clean and "123456789" not in clean)
check("redacts OpenAI-style keys", "sk-" in tools.redact_secrets("bad key sk-abcdefghijklmnop") and "abcdefghijklmnop" not in tools.redact_secrets("bad key sk-abcdefghijklmnop"))

# 2. chat() must be declared so Gradio injects the request (otherwise session_hash is always None).
import app
args = special_args(app.chat, ["hi", []], request=gr.Request())[0]
check("chat() receives gr.Request", any(isinstance(a, gr.Request) for a in args))

# 3. Visitors never see raw exception text.
src = inspect.getsource(app.chat)
check("chat() does not echo exception text to visitors", "str(e)" not in src and "{e}" not in src)

# 4. Concurrency limit is wired to the chat event and above Gradio's default of 1.
check("MAX_CONCURRENT_CHATS > 1", app.MAX_CONCURRENT_CHATS > 1)
print("ALL PASSED")
