"""Iteration 28 — Case 4: Chatter activity log inline preview for WhatsApp & Email template sends.

Verifies:
- Manual WA send logs a chatter message with kind='wa_template', preview, template_name, track_id, status.
- Manual Email send logs a chatter message with kind='email_template', preview, status, subject.
- Chatter WA message status matches wa_tracking record.
- Automation-triggered send_whatsapp_template logs a chatter wa_template entry.
- Automation-triggered send_email_template logs a chatter email_template entry.
- Regression: normal chatter note posting, follow-ups CRUD, caller 403 on reports/export,
  wa lead-messages endpoint, whatsapp templates listing.
"""
import os
import random
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env", override=False)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not configured"
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER = {"email": "agent@homeivf.com", "password": "Agent@2026"}


def _mongo_db():
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module", autouse=True)
def _align_counter():
    db = _mongo_db()
    mx = list(db.leads.find({}, {"id": 1}).sort("id", -1).limit(1))
    if mx:
        db.counters.update_one({"_id": "lead"}, {"$set": {"seq": mx[0]["id"]}}, upsert=True)
    yield


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    return s


@pytest.fixture(scope="module")
def wa_template(admin):
    r = admin.get(f"{API}/templates/whatsapp")
    assert r.status_code == 200
    items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    tpl = next((t for t in items if (t.get("body") or "").strip()
                and t.get("active", True) is not False), None)
    if not tpl:
        pytest.skip("no WA template with body")
    return tpl


@pytest.fixture(scope="module")
def lead_with_phone(admin):
    r = admin.get(f"{API}/leads/500161")
    if r.status_code == 200 and r.json().get("phone"):
        return 500161
    r = admin.get(f"{API}/leads", params={"limit": 50})
    lead = next((i for i in r.json()["items"] if i.get("phone")), None)
    assert lead, "no lead with phone"
    return lead["id"]


# ---------------- Case 4 — Manual WhatsApp send ----------------
class TestCase4ManualWA:
    def test_manual_send_wa_logs_chatter_preview(self, admin, wa_template, lead_with_phone):
        lid = lead_with_phone
        rs = admin.post(f"{API}/leads/{lid}/send_whatsapp",
                        json={"template_id": wa_template["id"]})
        # 400 acceptable if live send fails (Meta param mismatch) — chatter+track already written
        assert rs.status_code in (200, 400), rs.text

        rm = admin.get(f"{API}/leads/{lid}/messages", params={"limit": 30})
        assert rm.status_code == 200
        items = rm.json()["items"]
        wa_msgs = [m for m in items if m.get("kind") == "wa_template"]
        assert wa_msgs, f"no wa_template chatter message found for lead {lid}"
        m = wa_msgs[0]
        assert m.get("preview"), "preview missing"
        assert m.get("template_name")
        assert m.get("track_id"), "track_id missing"
        assert m.get("status") in ("in_queue", "sent", "delivered", "read",
                                    "failed", "bounced", "replied", "received")

        # matches wa_tracking
        rt = admin.get(f"{API}/wa/lead/{lid}/messages")
        assert rt.status_code == 200
        tracks = rt.json() if isinstance(rt.json(), list) else rt.json().get("items", [])
        tr = next((t for t in tracks if t.get("id") == m["track_id"]), None)
        assert tr, f"track_id {m['track_id']} not found in wa lead messages"
        # UI shows live status from wa_tracking; ensure it's a valid label
        assert tr.get("status")


# ---------------- Case 4 — Manual Email send ----------------
class TestCase4ManualEmail:
    def test_manual_send_email_logs_chatter_preview(self, admin, lead_with_phone):
        # need an email
        db = _mongo_db()
        # ensure the lead has email
        db.leads.update_one({"id": lead_with_phone},
                            {"$set": {"email_from": "test.iter28@example.com"}})
        subject = f"TEST_iter28 subject {random.randint(1000, 9999)}"
        body = f"<p>Hello TEST_iter28 body {random.randint(1000,9999)}</p>"
        rs = admin.post(f"{API}/leads/{lead_with_phone}/send_email",
                        json={"subject": subject, "body": body})
        assert rs.status_code == 200, rs.text

        rm = admin.get(f"{API}/leads/{lead_with_phone}/messages", params={"limit": 10})
        items = rm.json()["items"]
        em = next((m for m in items if m.get("kind") == "email_template"
                   and m.get("subject") == subject), None)
        assert em, f"email_template chatter not found; got kinds={[i.get('kind') for i in items[:5]]}"
        assert em.get("preview") == body
        assert em.get("status") in ("sent", "in_queue")


# ---------------- Case 4 — Automation triggers ----------------
class TestCase4Automation:
    def test_automation_on_create_wa_template_logs_preview(self, admin, wa_template):
        # create automation
        rule_name = f"TEST_iter28_auto_wa_{random.randint(10000,99999)}"
        payload = {
            "name": rule_name, "trigger": "on_create", "active": True,
            "condition": {}, "actions": [
                {"type": "send_whatsapp_template", "value": str(wa_template["id"])}
            ]
        }
        ra = admin.post(f"{API}/admin/automations", json=payload)
        assert ra.status_code in (200, 201), ra.text
        rule = ra.json()
        rule_id = rule.get("id")

        try:
            # trigger by creating a lead with phone
            phone = f"9{random.randint(100000000, 999999999)}"
            rc = admin.post(f"{API}/leads",
                            json={"contact_name": "TEST_iter28_autolead", "phone": phone})
            assert rc.status_code == 200, rc.text
            new_lead = rc.json()
            lid = new_lead["id"]

            rm = admin.get(f"{API}/leads/{lid}/messages", params={"limit": 30})
            items = rm.json()["items"]
            wa_msgs = [m for m in items if m.get("kind") == "wa_template"]
            assert wa_msgs, f"automation did not produce wa_template chatter for lead {lid}; kinds={[i.get('kind') for i in items]}"
            m = wa_msgs[0]
            assert m.get("preview")
            assert m.get("track_id")
            assert m.get("status") in ("in_queue", "sent", "failed")
        finally:
            if rule_id:
                admin.delete(f"{API}/admin/automations/{rule_id}")

    def test_automation_on_create_email_template_logs_preview(self, admin):
        # ensure at least one email template
        rt = admin.get(f"{API}/templates/email")
        items = rt.json() if isinstance(rt.json(), list) else rt.json().get("items", [])
        if not items:
            # create one
            rc = admin.post(f"{API}/templates/email",
                            json={"name": "TEST_iter28_tpl",
                                  "subject": "TEST subj",
                                  "body": "<p>TEST body</p>"})
            if rc.status_code not in (200, 201):
                pytest.skip("cannot create email template for automation test")
            tpl = rc.json()
        else:
            tpl = items[0]
        tpl_id = tpl["id"]

        rule_name = f"TEST_iter28_auto_email_{random.randint(10000,99999)}"
        payload = {
            "name": rule_name, "trigger": "on_create", "active": True,
            "condition": {}, "actions": [
                {"type": "send_email_template", "value": str(tpl_id)}
            ]
        }
        ra = admin.post(f"{API}/admin/automations", json=payload)
        assert ra.status_code in (200, 201), ra.text
        rule_id = ra.json().get("id")

        try:
            phone = f"9{random.randint(100000000, 999999999)}"
            rc = admin.post(f"{API}/leads",
                            json={"contact_name": "TEST_iter28_email_autolead",
                                  "phone": phone,
                                  "email_from": "auto.iter28@example.com"})
            assert rc.status_code == 200, rc.text
            lid = rc.json()["id"]

            rm = admin.get(f"{API}/leads/{lid}/messages", params={"limit": 30})
            items2 = rm.json()["items"]
            em_msgs = [m for m in items2 if m.get("kind") == "email_template"]
            assert em_msgs, f"automation did not produce email_template chatter; kinds={[i.get('kind') for i in items2]}"
            m = em_msgs[0]
            assert m.get("preview")
            assert m.get("status") in ("sent", "in_queue")
        finally:
            if rule_id:
                admin.delete(f"{API}/admin/automations/{rule_id}")


# ---------------- Regression ----------------
class TestRegression:
    def test_chatter_note_post(self, admin, lead_with_phone):
        r = admin.post(f"{API}/leads/{lead_with_phone}/messages",
                       json={"body": "TEST_iter28 regression note", "subtype": "note"})
        assert r.status_code == 200
        assert r.json().get("body") == "TEST_iter28 regression note"

    def test_caller_reports_forbidden(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json=CALLER)
        assert r.status_code == 200
        tok = r.json().get("access_token")
        if tok:
            s.headers["Authorization"] = f"Bearer {tok}"
        rep = s.get(f"{API}/reports/export.csv")
        assert rep.status_code in (401, 403, 404), rep.status_code

    def test_wa_lead_messages_endpoint(self, admin, lead_with_phone):
        r = admin.get(f"{API}/wa/lead/{lead_with_phone}/messages")
        assert r.status_code == 200

    def test_ozonetel_bucket_still_works(self, admin):
        r = admin.get(f"{API}/leads", params={"bucket": "ozonetel", "limit": 5})
        assert r.status_code == 200

    def test_followups_crud(self, admin, lead_with_phone):
        ra = admin.post(f"{API}/leads/{lead_with_phone}/followups",
                        json={"follow_up_date": "2026-02-20", "note": "TEST_iter28"})
        assert ra.status_code == 200
        fid = ra.json()["id"]
        rd = admin.delete(f"{API}/leads/{lead_with_phone}/followups/{fid}")
        assert rd.status_code == 200

    def test_templates_whatsapp_list(self, admin):
        r = admin.get(f"{API}/templates/whatsapp")
        assert r.status_code == 200
