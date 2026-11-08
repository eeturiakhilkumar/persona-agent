"""Failure-path checks for lead handoffs and escalation states. Run: python tests/test_handoff.py"""
import os, sys
os.environ["USER_NAME"] = "Test User"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for k in ("PUSHOVER_USER","PUSHOVER_TOKEN","TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID","FIREBASE_CREDENTIALS_JSON"):
    os.environ[k] = ""
import tools
from unittest import mock

class Col:
    def __init__(s, fail): s.fail=fail; s.docs={}
    def add(s, p):
        if s.fail: raise RuntimeError("firestore down")
        s.docs[len(s.docs)]=p
    def document(s, i): return Doc(s, i)
class Doc:
    def __init__(s,c,i): s.c=c; s.i=i
    def set(s,p): s.c.docs[s.i]=dict(p)
    def update(s,p): s.c.docs.setdefault(s.i,{}).update(p)
class DB:
    def __init__(s, fail=False): s.cols={}; s.fail=fail
    def collection(s,n): return s.cols.setdefault(n, Col(s.fail))

def check(name, cond):
    print(("PASS " if cond else "FAIL ")+name); 
    if not cond: sys.exit(1)

# 1. nothing configured -> logged_locally
tools.db=None; tools.pushover_token=tools.pushover_user=""
r=tools.record_user_details("a@b.com","Ann")
check("no db/push -> LOGGED_LOCALLY", r.startswith("LOGGED_LOCALLY"))
# 2. firestore ok -> OK
tools.db=DB(); r=tools.record_user_details("a@b.com","Ann")
check("firestore ok -> OK", r.startswith("OK:"))
# 3. firestore down, no push -> NOT_SAVED
tools.db=DB(fail=True); r=tools.record_user_details("a@b.com","Ann")
check("firestore down -> NOT_SAVED", r.startswith("NOT_SAVED") and "Do NOT tell" in r)
# 4. firestore down but push works -> OK
tools.pushover_token=tools.pushover_user="x"
with mock.patch.object(tools.requests,"post",return_value=mock.Mock(status_code=200)):
    r=tools.record_user_details("a@b.com","Ann")
check("firestore down + push ok -> OK", r.startswith("OK:"))
# 5. push rejected, no db -> NOT_SAVED
tools.db=None
with mock.patch.object(tools.requests,"post",return_value=mock.Mock(status_code=400)):
    r=tools.record_user_details("a@b.com","Ann")
check("push rejected, no db -> NOT_SAVED", r.startswith("NOT_SAVED"))
with mock.patch.object(tools.requests,"post",side_effect=TimeoutError()):
    r=tools.tool_map["capture_project_scope"](problem_statement="Build a dashboard for sales")
check("push timeout, no db -> NOT_SAVED", r.startswith("NOT_SAVED"))
tools.pushover_token=tools.pushover_user=""; tools.db=DB()
# 6. validation
check("bad email rejected", tools.record_user_details("nope").startswith("NOT_SAVED"))
check("empty recruiter rejected", tools.tool_map["log_recruiter_opportunity"]().startswith("NOT_SAVED"))
check("recruiter with company ok", tools.tool_map["log_recruiter_opportunity"](company="Acme").startswith("OK:"))
check("short project rejected", tools.tool_map["capture_project_scope"](problem_statement="app").startswith("NOT_SAVED"))
check("blank question rejected", tools.record_unknown_question("  ").startswith("NOT_SAVED"))
check("blank escalation rejected", tools.escalate_to_human("").startswith("NOT_SAVED"))
nothing_stored = not tools.db.cols.get("general_contacts") or not tools.db.cols["general_contacts"].docs
check("rejected leads were not stored", nothing_stored and not tools.db.cols.get("project_leads"))
# 7. escalation states
from limits import RateLimiter
def _reset(): tools._escalation_session_limiter = RateLimiter(2, 1800)
_reset()
tools.db=DB()
r=tools.escalate_to_human("Can you relocate?")  # telegram not configured
esc=tools.db.cols["escalations"].docs
st=list(esc.values())[0]
check("telegram unconfigured -> status failed", st["status"]=="failed" and "failed_at" in st and "unavailable" in r)
os.environ["TELEGRAM_BOT_TOKEN"]="t"; os.environ["TELEGRAM_CHAT_ID"]="1"
tools.db=DB(); _reset()
with mock.patch.object(tools.requests,"post",return_value=mock.Mock(status_code=200, json=lambda: {"ok": True})):
    r=tools.escalate_to_human("Can you relocate?")
eid=r.split(":",1)[1]
check("telegram ok -> WAIT + delivered", r.startswith("WAIT_FOR_HUMAN:") and tools.db.cols["escalations"].docs[eid]["status"]=="delivered")
tools.set_escalation_status(eid,"expired")
d=tools.db.cols["escalations"].docs[eid]
check("expired state + timestamp", d["status"]=="expired" and "expired_at" in d)
tools.set_escalation_status(eid,"resolved",reply="yes")
check("resolved state + reply", tools.db.cols["escalations"].docs[eid]["reply"]=="yes")
with mock.patch.object(tools.requests,"post",return_value=mock.Mock(status_code=200, json=lambda: {"ok": False})):
    tools.db=DB(); _reset(); r=tools.escalate_to_human("Another question")
check("telegram rejects -> failed", list(tools.db.cols["escalations"].docs.values())[0]["status"]=="failed")
print("ALL PASSED")
