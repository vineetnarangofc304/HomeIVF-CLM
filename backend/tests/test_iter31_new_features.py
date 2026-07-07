"""Iter31: Case 1 Gmail PKCE, Case 5 field options + Quick Reply automation webhook."""
import hmac
import hashlib
import json
import os
import time

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASS = "HomeIVF@2026"

TS = int(time.time())
TEST_WAMID = f"TEST_iter31_wamid_{TS}"
TEST_APP_SECRET = f"TEST_iter31_secret_{TS}"
TEST_PHONE_DIGITS = f"9998{TS % 1000000:06d}"[-10:]


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


# ---------------- Case 1: Gmail PKCE ----------------
class TestGmailPKCE:
    def test_auth_url_stores_code_verifier(self, admin_client, mongo):
        # Clean prior states
        mongo.oauth_states.delete_many({"provider": "gmail"})
        r = admin_client.get(f"{BASE_URL}/api/admin/gmail/auth-url")
        assert r.status_code == 200, r.text
        url = r.json().get("url")
        assert url and "code_challenge" in url, f"missing code_challenge in url: {url}"
        st = mongo.oauth_states.find_one({"provider": "gmail"})
        assert st is not None, "no oauth_states doc saved"
        cv = st.get("code_verifier")
        assert cv and isinstance(cv, str) and len(cv) >= 40, f"code_verifier bad: {cv!r}"

    def test_callback_bad_code_redirects_not_500(self):
        r = requests.get(f"{BASE_URL}/api/oauth/gmail/callback",
                         params={"code": "INVALID_CODE", "state": "nostate"},
                         allow_redirects=False, timeout=30)
        assert r.status_code in (302, 307), f"expected redirect, got {r.status_code} {r.text[:200]}"
        loc = r.headers.get("location", "")
        assert "tab=Email" in loc and "gmail=" in loc


# ---------------- Case 5A: field options ----------------
class TestFieldOptions:
    def test_lead_field_options(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/catalogs/lead-field-options")
        assert r.status_code == 200, r.text
        data = r.json()
        opts = data.get("options") or []
        assert len(opts) >= 15, f"expected >=15 options, got {len(opts)}"
        keys = {o["key"] for o in opts}
        for k in ("contact_name", "phone", "email_from"):
            assert k in keys, f"missing standard field {k}"
        assert all("label" in o and "group" in o for o in opts)


# ---------------- Case 5B: WhatsApp webhook Quick Reply + status lifecycle ----------------
@pytest.fixture(scope="module")
def wa_seed(mongo):
    """Seed lead + template with automation Quick Reply + wa_tracking + set app_secret."""
    # Snapshot & set app_secret
    orig = mongo.settings.find_one({"key": "whatsapp_cloud"})
    if orig:
        mongo.settings.update_one({"key": "whatsapp_cloud"},
            {"$set": {"__iter31_orig_secret": orig.get("app_secret"), "app_secret": TEST_APP_SECRET}})
    else:
        mongo.settings.insert_one({"key": "whatsapp_cloud", "app_secret": TEST_APP_SECRET,
                                   "__iter31_created": True})

    # Automation
    max_a = mongo.automations.find_one(sort=[("id", -1)]) or {}
    aid = (max_a.get("id") or 0) + 1
    mongo.automations.insert_one({
        "id": aid, "name": f"TEST_iter31_auto_{TS}", "trigger": "manual", "active": True,
        "actions": [{"type": "set_lead_stage", "value": "TEST_STAGE_ITER31"}],
        "__iter31_test": True,
    })

    # Lead
    max_l = mongo.leads.find_one(sort=[("id", -1)]) or {}
    lid = (max_l.get("id") or 0) + 1
    mongo.leads.insert_one({
        "id": lid, "name": f"TEST_iter31_lead_{TS}", "contact_name": f"TEST_iter31_lead_{TS}",
        "phone": "+91" + TEST_PHONE_DIGITS, "phone_digits": TEST_PHONE_DIGITS,
        "active": True, "ozonetel_lead": False, "in_pipeline": True,
        "lead_stage": "New", "tags": [], "write_date": "2026-01-01T00:00:00Z",
        "__iter31_test": True,
    })
    # keep counters sane
    mongo.counters.update_one({"_id": "lead"}, {"$max": {"seq": lid}}, upsert=True)

    # Template with a Quick Reply button
    max_t = mongo.templates_whatsapp.find_one(sort=[("id", -1)]) or {}
    tid = (max_t.get("id") or 0) + 1
    mongo.templates_whatsapp.insert_one({
        "id": tid, "name": f"TEST_iter31_tmpl_{TS}", "body": "hello {{1}}",
        "buttons": [{"type": "Quick Reply", "text": "Yes", "automation_id": aid}],
        "__iter31_test": True,
    })

    # wa_tracking outbound sent
    max_w = mongo.wa_tracking.find_one(sort=[("id", -1)]) or {}
    wid = (max_w.get("id") or 0) + 1
    mongo.wa_tracking.insert_one({
        "id": wid, "wamid": TEST_WAMID, "status": "sent",
        "status_at": "2026-01-01T00:00:00Z",
        "lead_id": lid, "template_id": tid,
        "status_history": [{"status": "sent", "at": "2026-01-01T00:00:00Z"}],
        "__iter31_test": True,
    })

    yield {"lead_id": lid, "template_id": tid, "wa_id": wid, "wamid": TEST_WAMID, "auto_id": aid}

    # cleanup
    mongo.leads.delete_one({"id": lid})
    mongo.templates_whatsapp.delete_one({"id": tid})
    mongo.wa_tracking.delete_one({"id": wid})
    mongo.automations.delete_one({"id": aid})
    if orig:
        restore = {"app_secret": orig.get("app_secret")} if orig.get("app_secret") is not None else {}
        unset = {"__iter31_orig_secret": ""}
        if not restore:
            unset["app_secret"] = ""
        op = {"$unset": unset}
        if restore:
            op["$set"] = restore
        mongo.settings.update_one({"key": "whatsapp_cloud"}, op)
    else:
        mongo.settings.delete_one({"key": "whatsapp_cloud", "__iter31_created": True})


def _sign_post(body_dict, secret=TEST_APP_SECRET, bad=False):
    raw = json.dumps(body_dict).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if bad:
        sig = "0" * 64
    return requests.post(
        f"{BASE_URL}/api/webhooks/whatsapp",
        data=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sig}"},
        timeout=30,
    )


def _status_body(wamid, status):
    return {"entry": [{"changes": [{"value": {"statuses": [{"id": wamid, "status": status}]}}]}]}


def _inbound_button_body(from_phone, wamid, text="Yes"):
    return {"entry": [{"changes": [{"value": {
        "messages": [{
            "from": from_phone, "id": wamid, "type": "button",
            "button": {"text": text, "payload": text},
        }]
    }}]}]}


class TestWebhookStatusLifecycle:
    def test_sent_to_delivered(self, wa_seed, mongo):
        r = _sign_post(_status_body(wa_seed["wamid"], "delivered"))
        assert r.status_code == 200, r.text
        assert mongo.wa_tracking.find_one({"id": wa_seed["wa_id"]})["status"] == "delivered"

    def test_delivered_to_read(self, wa_seed, mongo):
        r = _sign_post(_status_body(wa_seed["wamid"], "read"))
        assert r.status_code == 200
        assert mongo.wa_tracking.find_one({"id": wa_seed["wa_id"]})["status"] == "read"

    def test_bad_signature_401(self, wa_seed, mongo):
        before = mongo.wa_tracking.find_one({"id": wa_seed["wa_id"]})["status"]
        r = _sign_post(_status_body(wa_seed["wamid"], "delivered"), bad=True)
        assert r.status_code == 401
        after = mongo.wa_tracking.find_one({"id": wa_seed["wa_id"]})["status"]
        assert before == after


class TestQuickReplyAutomation:
    def test_quick_reply_triggers_automation_and_marks_replied(self, wa_seed, mongo):
        wamid_in = f"TEST_iter31_inbound_{TS}"
        r = _sign_post(_inbound_button_body("91" + TEST_PHONE_DIGITS, wamid_in, text="Yes"))
        assert r.status_code == 200, r.text

        # wa_tracking marked replied
        rec = mongo.wa_tracking.find_one({"id": wa_seed["wa_id"]})
        assert rec["status"] == "replied", f"expected replied, got {rec['status']}"

        # lead updated by automation (set_lead_stage)
        lead = mongo.leads.find_one({"id": wa_seed["lead_id"]})
        assert lead.get("lead_stage") == "TEST_STAGE_ITER31", f"lead_stage not applied: {lead.get('lead_stage')}"

        # chatter log for quick reply exists
        msg = mongo.messages.find_one({
            "lead_id": wa_seed["lead_id"],
            "body": {"$regex": "WhatsApp Quick Reply"},
        }, sort=[("id", -1)])
        assert msg is not None, "no quick reply chatter message logged"
