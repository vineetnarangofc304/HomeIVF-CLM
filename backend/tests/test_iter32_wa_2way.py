"""Iter32: WhatsApp 2-way chat fixes.
- Inbound webhook auto-creates a wa_channel for a NEW phone number (no collision).
- Second inbound from same number reuses the same channel.
- Bad HMAC signature -> 401 (no channel created).
- Inbound into an EXISTING thread appends to it (regression).
- Reply endpoint returns 200 with status 'pending_api_credentials' when WA not configured.
"""
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
TEST_APP_SECRET = f"TEST_iter32_secret_{TS}"
# Fresh number that won't match any existing channel
NEW_PHONE = f"9199990001{TS % 100:02d}"  # e.g. 919999000142
NEW_DIGITS = NEW_PHONE[-10:]


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


@pytest.fixture(scope="module")
def wa_secret(mongo):
    """Temporarily set app_secret for HMAC verification, snapshot and restore after."""
    orig = mongo.settings.find_one({"key": "whatsapp_cloud"}) or {}
    orig_secret = orig.get("app_secret")
    orig_at = orig.get("access_token")
    orig_pn = orig.get("phone_number_id")
    # Force NOT configured for reply test + set our own secret
    mongo.settings.update_one(
        {"key": "whatsapp_cloud"},
        {"$set": {"app_secret": TEST_APP_SECRET, "access_token": None, "phone_number_id": None}},
        upsert=True,
    )
    yield TEST_APP_SECRET
    # Restore
    restore = {"app_secret": orig_secret, "access_token": orig_at, "phone_number_id": orig_pn}
    mongo.settings.update_one({"key": "whatsapp_cloud"}, {"$set": restore})


def _sig(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _inbound_payload(from_num: str, text: str, wamid: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba1",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "messages": [{"from": from_num, "id": wamid, "type": "text",
                                  "text": {"body": text}, "timestamp": str(int(time.time()))}],
                },
                "field": "messages",
            }],
        }],
    }


@pytest.fixture(scope="module", autouse=True)
def cleanup(mongo):
    yield
    # Clean up test-created channels + messages
    chs = list(mongo.wa_channels.find({"phone_digits": {"$regex": NEW_DIGITS + "$"}}, {"id": 1}))
    ids = [c["id"] for c in chs]
    if ids:
        mongo.wa_messages.delete_many({"channel_id": {"$in": ids}})
        mongo.wa_channels.delete_many({"id": {"$in": ids}})


class TestWebhookAutoCreate:
    def test_bad_signature_rejected(self, wa_secret, mongo):
        payload = _inbound_payload(NEW_PHONE, "should not store", f"TEST_iter32_bad_{TS}")
        raw = json.dumps(payload).encode()
        r = requests.post(f"{BASE_URL}/api/webhooks/whatsapp",
                          data=raw, headers={"Content-Type": "application/json",
                                             "X-Hub-Signature-256": "sha256=deadbeef"}, timeout=30)
        assert r.status_code == 401, r.text
        assert mongo.wa_channels.count_documents({"phone_digits": {"$regex": NEW_DIGITS + "$"}}) == 0

    def test_inbound_new_number_creates_channel(self, wa_secret, mongo):
        # baseline: no channel exists for this number
        assert mongo.wa_channels.count_documents({"phone_digits": {"$regex": NEW_DIGITS + "$"}}) == 0
        max_before = (mongo.wa_channels.find_one({}, sort=[("id", -1)], projection={"id": 1}) or {}).get("id", 0)

        wamid = f"TEST_iter32_new_{TS}_1"
        payload = _inbound_payload(NEW_PHONE, "hello brand new number", wamid)
        raw = json.dumps(payload).encode()
        r = requests.post(f"{BASE_URL}/api/webhooks/whatsapp",
                          data=raw, headers={"Content-Type": "application/json",
                                             "X-Hub-Signature-256": _sig(wa_secret, raw)}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("stored") == 1, body

        ch = mongo.wa_channels.find_one({"phone_digits": {"$regex": NEW_DIGITS + "$"}})
        assert ch is not None, "new channel was not created"
        assert ch["id"] > max_before, f"new channel id {ch['id']} did not exceed previous max {max_before}"
        assert ch.get("created_via") == "inbound_webhook"

        msg = mongo.wa_messages.find_one({"wamid": wamid})
        assert msg is not None, "inbound message not stored"
        assert msg["channel_id"] == ch["id"]
        assert msg["direction"] == "inbound"
        assert msg["status"] == "received"
        assert "hello brand new number" in msg["body"]

    def test_inbound_same_number_reuses_channel(self, wa_secret, mongo):
        before = list(mongo.wa_channels.find({"phone_digits": {"$regex": NEW_DIGITS + "$"}}, {"id": 1}))
        assert len(before) == 1, before
        ch_id = before[0]["id"]

        wamid = f"TEST_iter32_new_{TS}_2"
        payload = _inbound_payload(NEW_PHONE, "second message reuses thread", wamid)
        raw = json.dumps(payload).encode()
        r = requests.post(f"{BASE_URL}/api/webhooks/whatsapp",
                          data=raw, headers={"Content-Type": "application/json",
                                             "X-Hub-Signature-256": _sig(wa_secret, raw)}, timeout=30)
        assert r.status_code == 200, r.text

        after = list(mongo.wa_channels.find({"phone_digits": {"$regex": NEW_DIGITS + "$"}}, {"id": 1}))
        assert len(after) == 1, f"expected 1 channel, got {len(after)}: {after}"
        assert after[0]["id"] == ch_id, "channel id changed / duplicated"

        msg = mongo.wa_messages.find_one({"wamid": wamid})
        assert msg is not None and msg["channel_id"] == ch_id


class TestWebhookExistingThread:
    def test_inbound_existing_channel_appends(self, wa_secret, mongo):
        # Pick an existing channel with a phone_digits
        existing = mongo.wa_channels.find_one({"phone_digits": {"$exists": True, "$ne": None}, "created_via": {"$ne": "inbound_webhook"}})
        if not existing or not existing.get("phone_digits"):
            pytest.skip("no existing channel with phone_digits to test regression")
        digits = existing["phone_digits"]
        if len(digits) < 8:
            pytest.skip("existing channel digits too short")
        ch_id = existing["id"]
        before_count = mongo.wa_channels.count_documents({"phone_digits": digits})
        wamid = f"TEST_iter32_existing_{TS}"
        payload = _inbound_payload("91" + digits, "regression inbound", wamid)
        raw = json.dumps(payload).encode()
        r = requests.post(f"{BASE_URL}/api/webhooks/whatsapp",
                          data=raw, headers={"Content-Type": "application/json",
                                             "X-Hub-Signature-256": _sig(wa_secret, raw)}, timeout=30)
        assert r.status_code == 200, r.text
        after_count = mongo.wa_channels.count_documents({"phone_digits": digits})
        assert after_count == before_count, "duplicate channel created for existing number"
        msg = mongo.wa_messages.find_one({"wamid": wamid})
        assert msg is not None
        assert msg["channel_id"] == ch_id
        # cleanup this test message
        mongo.wa_messages.delete_one({"wamid": wamid})


class TestReplyEndpoint:
    def test_reply_not_configured_returns_queued(self, admin_client, wa_secret, mongo):
        # Use the new channel we auto-created
        ch = mongo.wa_channels.find_one({"phone_digits": {"$regex": NEW_DIGITS + "$"}})
        assert ch is not None, "prerequisite: auto-created channel missing"
        ch_id = ch["id"]

        r = admin_client.post(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/send",
                              json={"body": f"TEST_iter32 reply {TS}"}, timeout=30)
        assert r.status_code == 200, f"expected 200 not 500 when unconfigured: {r.status_code} {r.text}"
        data = r.json()
        assert data.get("status") == "pending_api_credentials", data
        assert data.get("direction") == "outbound"

        # Verify queued
        q = mongo.outbound_queue.find_one({"wa_channel_id": ch_id, "body": f"TEST_iter32 reply {TS}"})
        assert q is not None, "message not queued to outbound_queue"
        assert q.get("status") == "pending_api_credentials"
        mongo.outbound_queue.delete_one({"_id": q["_id"]})

    def test_reply_channel_not_found(self, admin_client):
        r = admin_client.post(f"{BASE_URL}/api/whatsapp/channels/99999999/send",
                              json={"body": "nope"}, timeout=30)
        assert r.status_code == 404, r.text


class TestListingIntegration:
    def test_new_channel_appears_in_list(self, admin_client, mongo):
        ch = mongo.wa_channels.find_one({"phone_digits": {"$regex": NEW_DIGITS + "$"}})
        assert ch is not None
        r = admin_client.get(f"{BASE_URL}/api/whatsapp/channels", params={"search": NEW_DIGITS[-6:], "limit": 30}, timeout=30)
        assert r.status_code == 200, r.text
        items = r.json().get("items", [])
        ids = [i["id"] for i in items]
        assert ch["id"] in ids, f"new channel not found via search: ids={ids}"

    def test_messages_endpoint_returns_inbound(self, admin_client, mongo):
        ch = mongo.wa_channels.find_one({"phone_digits": {"$regex": NEW_DIGITS + "$"}})
        assert ch is not None
        r = admin_client.get(f"{BASE_URL}/api/whatsapp/channels/{ch['id']}/messages", timeout=30)
        assert r.status_code == 200
        items = r.json().get("items", [])
        directions = {m.get("direction") for m in items}
        assert "inbound" in directions, f"no inbound in thread: {items}"
