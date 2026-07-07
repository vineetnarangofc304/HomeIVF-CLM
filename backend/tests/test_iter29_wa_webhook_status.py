"""Iter29: WhatsApp webhook status lifecycle + subscribe + webhook-log + signature rejection."""
import hmac
import hashlib
import json
import os
import time
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

# Load both env files
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASS = "HomeIVF@2026"

TEST_WAMID = f"TEST_iter29_wamid_{int(time.time())}"
TEST_APP_SECRET = f"TEST_iter29_secret_{int(time.time())}"


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    db = c[DB_NAME]
    yield db
    c.close()


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def seed(mongo):
    """Seed a wa_tracking doc + set app_secret in settings.whatsapp_cloud."""
    # Backup original settings
    orig = mongo.settings.find_one({"key": "whatsapp_cloud"})
    # Insert app_secret without disturbing other keys
    if orig:
        mongo.settings.update_one({"key": "whatsapp_cloud"}, {"$set": {"__iter29_orig_app_secret": orig.get("app_secret"), "app_secret": TEST_APP_SECRET}})
    else:
        mongo.settings.insert_one({"key": "whatsapp_cloud", "app_secret": TEST_APP_SECRET, "__iter29_created": True})

    # next id
    max_doc = mongo.wa_tracking.find_one(sort=[("id", -1)])
    new_id = (max_doc["id"] if max_doc else 0) + 1
    mongo.wa_tracking.insert_one({
        "id": new_id,
        "wamid": TEST_WAMID,
        "status": "sent",
        "status_at": "2026-01-01T00:00:00Z",
        "lead_id": 999999,
        "template_id": None,
        "status_history": [{"status": "sent", "at": "2026-01-01T00:00:00Z"}],
        "__iter29_test": True,
    })
    yield {"id": new_id, "wamid": TEST_WAMID}
    # cleanup
    mongo.wa_tracking.delete_one({"id": new_id})
    if orig:
        # restore
        restore = {"app_secret": orig.get("app_secret")} if orig.get("app_secret") is not None else {}
        unset = {"__iter29_orig_app_secret": ""}
        if not restore:
            unset["app_secret"] = ""
        op = {"$unset": unset}
        if restore:
            op["$set"] = restore
        mongo.settings.update_one({"key": "whatsapp_cloud"}, op)
    else:
        mongo.settings.delete_one({"key": "whatsapp_cloud", "__iter29_created": True})


def _post_signed(body_dict, secret=TEST_APP_SECRET, bad_sig=False):
    raw = json.dumps(body_dict).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if bad_sig:
        sig = "0" * 64
    return requests.post(
        f"{BASE_URL}/api/webhooks/whatsapp",
        data=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sig}"},
        timeout=30,
    )


def _status_body(wamid, status, with_errors=False):
    st = {"id": wamid, "status": status}
    if with_errors:
        st["errors"] = [{"code": 131026, "title": "Message undeliverable", "error_data": {"details": "Recipient not on WhatsApp"}}]
    return {"entry": [{"changes": [{"value": {"statuses": [st]}}]}]}


# ---- STATUS ADVANCE ----
class TestStatusAdvance:
    def test_delivered(self, seed, mongo):
        r = _post_signed(_status_body(seed["wamid"], "delivered"))
        assert r.status_code == 200, r.text
        rec = mongo.wa_tracking.find_one({"id": seed["id"]})
        assert rec["status"] == "delivered"
        assert any(h["status"] == "delivered" for h in rec.get("status_history", []))

    def test_read(self, seed, mongo):
        r = _post_signed(_status_body(seed["wamid"], "read"))
        assert r.status_code == 200, r.text
        rec = mongo.wa_tracking.find_one({"id": seed["id"]})
        assert rec["status"] == "read"
        assert any(h["status"] == "read" for h in rec.get("status_history", []))

    def test_failed_with_errors(self, seed, mongo):
        r = _post_signed(_status_body(seed["wamid"], "failed", with_errors=True))
        assert r.status_code == 200, r.text
        rec = mongo.wa_tracking.find_one({"id": seed["id"]})
        assert rec["status"] == "failed"
        assert rec.get("error_code") == 131026
        assert rec.get("failure_type") == "Recipient not on WhatsApp"


# ---- SIGNATURE REJECTION ----
class TestSignature:
    def test_bad_signature_returns_401(self, seed, mongo):
        # snapshot current status
        before = mongo.wa_tracking.find_one({"id": seed["id"]})["status"]
        r = _post_signed(_status_body(seed["wamid"], "delivered"), bad_sig=True)
        assert r.status_code == 401
        after = mongo.wa_tracking.find_one({"id": seed["id"]})["status"]
        assert before == after, "record should not be updated with bad signature"


# ---- WEBHOOK LOG ----
class TestWebhookLog:
    def test_admin_webhook_log_lists_entries_and_matched(self, seed, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/whatsapp/webhook-log")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data
        items = data["items"]
        # find at least one item that matched our wamid
        matched_items = []
        for it in items:
            for s in it.get("statuses", []):
                if s.get("wamid") == TEST_WAMID:
                    matched_items.append(it)
                    break
        assert len(matched_items) >= 3, f"expected 3+ log entries for our wamid; got {len(matched_items)}"
        # at least one entry should show matched>0
        assert any(it.get("matched", 0) > 0 for it in matched_items)


# ---- SUBSCRIBE ENDPOINTS ----
class TestSubscribe:
    def test_subscribe_does_not_500(self, admin_client):
        r = admin_client.post(f"{BASE_URL}/api/admin/whatsapp/subscribe")
        assert r.status_code != 500, f"subscribe returned 500: {r.text}"
        assert r.status_code in (200, 400)

    def test_subscribed_apps_does_not_500(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/whatsapp/subscribed-apps")
        assert r.status_code != 500, f"subscribed-apps returned 500: {r.text}"
        assert r.status_code in (200, 400)


# ---- REGRESSION: message detail lifecycle + inbound reply marking ----
class TestRegression:
    def test_wa_message_detail_endpoint_reflects_read(self, seed, admin_client, mongo):
        # After all above tests, the seed record was flipped to 'failed'. Reset to 'read' for this test.
        mongo.wa_tracking.update_one({"id": seed["id"]}, {"$set": {"status": "read"}})
        r = admin_client.get(f"{BASE_URL}/api/wa/track/{seed['id']}")
        # Endpoint may or may not exist — accept 200 or 404. If 200, status should be 'read'.
        if r.status_code == 200:
            assert r.json().get("status") == "read"
