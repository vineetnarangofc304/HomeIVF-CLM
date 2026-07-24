"""Iter33 — Case 1 (Gmail sender name) + Case 2 Phase 2A WhatsApp Workspace overhaul.

Coverage:
- POST /api/admin/gmail/sender-name  (+ GET /api/admin/gmail/status)
- GET  /api/whatsapp/channels (filter=all|unread|interested, search, pagination)
- GET  /api/whatsapp/unread-summary
- Inbound signed webhook increments unread_count; POST /api/whatsapp/channels/{id}/read resets
- GET  /api/whatsapp/channels/{id}/messages?search / ?starred=true
- POST /api/whatsapp/messages/{id}/star | /pin | /react
- POST /api/whatsapp/channels/{id}/category  (tags matching lead + advances stage)
- POST /api/whatsapp/channels/{id}/send  (reply_to snippet stored)
- POST /api/whatsapp/media/upload + GET /api/whatsapp/media (401 without token)
- Inbound reaction webhook sets emoji on target message, no chat line created
"""
import hashlib
import hmac
import io
import json
import os
import re
import time
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://ivf-lead-ops.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASS = "HomeIVF@2026"

TEST_PREFIX = "TEST_iter33"


# ------------------------- fixtures -------------------------
@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    tok = r.json()["access_token"]
    s.headers.update({"Authorization": f"Bearer {tok}"})
    s.token = tok
    return s


@pytest.fixture(scope="module")
def app_secret(admin):
    """Fetch current whatsapp_cloud.app_secret via a proxy: read from admin diag or settings via admin."""
    # Read config via internal helper: use admin whatsapp status (no secret exposed).
    # Fetch app_secret from DB directly through settings endpoint if available; else use env fallback.
    r = admin.get(f"{BASE_URL}/api/admin/settings", timeout=20)
    if r.status_code == 200:
        j = r.json() or {}
        wa = j.get("whatsapp_cloud") if isinstance(j, dict) else None
        if isinstance(wa, dict):
            return wa.get("app_secret") or None
    return None


@pytest.fixture(scope="module")
def seed_channel_and_lead(admin):
    """Create a lead + wa_channel with a matching phone_digits so Interested category flow works.
    We seed via public APIs so DB stays clean.
    """
    digits = f"9199{int(time.time()) % 100000000:08d}"  # unique 12-digit number
    phone_digits10 = digits[-10:]
    # Create lead
    r = admin.post(f"{BASE_URL}/api/leads", json={
        "name": f"{TEST_PREFIX}_lead_{uuid.uuid4().hex[:6]}",
        "contact_name": "Iter33 Interested",
        "phone": "+" + digits,
        "mobile": "+" + digits,
    }, timeout=30)
    assert r.status_code in (200, 201), f"lead create {r.status_code} {r.text[:300]}"
    lead = r.json()
    lead_id = lead["id"]

    # Seed a channel by sending an inbound signed webhook, which auto-creates the channel.
    # This requires the app_secret; if unavailable, skip category-related tests below.
    # We still create a lightweight channel row via admin quick_reply? No such endpoint — use webhook path.
    yield {"lead_id": lead_id, "phone_digits": phone_digits10, "digits_full": digits}

    # Teardown — best-effort cleanup
    try:
        admin.delete(f"{BASE_URL}/api/leads/{lead_id}", timeout=15)
    except Exception:
        pass


def _sign(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _inbound_payload(from_digits: str, text: str, wamid: str = None):
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": from_digits,
                        "id": wamid or f"wamid.TEST_{uuid.uuid4().hex[:16]}",
                        "type": "text",
                        "text": {"body": text},
                    }]
                }
            }]
        }]
    }


def _reaction_payload(from_digits: str, target_wamid: str, emoji: str):
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": from_digits,
                        "id": f"wamid.RX_{uuid.uuid4().hex[:12]}",
                        "type": "reaction",
                        "reaction": {"message_id": target_wamid, "emoji": emoji},
                    }]
                }
            }]
        }]
    }


# ============================================================
# CASE 1 — Gmail sender name
# ============================================================
class TestGmailSenderName:
    def test_set_sender_name(self, admin):
        r = admin.post(f"{BASE_URL}/api/admin/gmail/sender-name", json={"sender_name": "HomeIVF"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "sender_name": "HomeIVF"}

    def test_status_reflects_sender_name(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/gmail/status", timeout=15)
        assert r.status_code == 200
        assert r.json().get("sender_name") == "HomeIVF"

    def test_empty_defaults_to_homeivf(self, admin):
        r = admin.post(f"{BASE_URL}/api/admin/gmail/sender-name", json={"sender_name": "   "}, timeout=15)
        assert r.status_code == 200
        assert r.json()["sender_name"] == "HomeIVF"


# ============================================================
# WA — channels list & filters & unread-summary
# ============================================================
class TestChannelsListing:
    def test_list_default(self, admin):
        r = admin.get(f"{BASE_URL}/api/whatsapp/channels?filter=all&page=1&limit=20", timeout=20)
        assert r.status_code == 200
        j = r.json()
        assert set(["items", "total", "page", "limit"]).issubset(j.keys())
        assert isinstance(j["items"], list)

    def test_unread_filter_only_unread(self, admin):
        r = admin.get(f"{BASE_URL}/api/whatsapp/channels?filter=unread&limit=50", timeout=20)
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert (it.get("unread_count") or 0) > 0, f"filter=unread returned zero-unread item {it.get('id')}"

    def test_interested_filter(self, admin):
        r = admin.get(f"{BASE_URL}/api/whatsapp/channels?filter=interested&limit=50", timeout=20)
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it.get("category") == "interested"

    def test_unread_summary_shape(self, admin):
        r = admin.get(f"{BASE_URL}/api/whatsapp/unread-summary", timeout=20)
        assert r.status_code == 200
        j = r.json()
        assert "total_unread" in j and "unread_chats" in j and "recent" in j
        assert isinstance(j["recent"], list)


# ============================================================
# WA — unread lifecycle via signed inbound webhook
# ============================================================
class TestUnreadLifecycle:
    def test_inbound_increments_unread_and_read_resets(self, admin, app_secret, seed_channel_and_lead):
        if not app_secret:
            pytest.skip("app_secret unavailable via admin settings endpoint")
        digits_full = seed_channel_and_lead["digits_full"]
        pd10 = seed_channel_and_lead["phone_digits"]
        payload = _inbound_payload(digits_full, f"{TEST_PREFIX} hello inbound {uuid.uuid4().hex[:6]}")
        raw = json.dumps(payload).encode()
        r = requests.post(f"{BASE_URL}/api/webhooks/whatsapp", data=raw,
                          headers={"X-Hub-Signature-256": _sign(app_secret, raw), "Content-Type": "application/json"},
                          timeout=20)
        assert r.status_code == 200, r.text

        # Locate the auto-created channel by phone_digits via search
        r2 = admin.get(f"{BASE_URL}/api/whatsapp/channels?search={pd10}&limit=5", timeout=20)
        assert r2.status_code == 200
        items = r2.json()["items"]
        assert items, "channel not auto-created for seeded phone_digits"
        ch = items[0]
        ch_id = ch["id"]
        assert (ch.get("unread_count") or 0) >= 1

        # unread-summary reflects it
        s = admin.get(f"{BASE_URL}/api/whatsapp/unread-summary", timeout=15).json()
        assert s["total_unread"] >= 1

        # mark read → 0
        rr = admin.post(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/read", timeout=15)
        assert rr.status_code == 200 and rr.json().get("ok") is True

        r3 = admin.get(f"{BASE_URL}/api/whatsapp/channels?search={pd10}&limit=5", timeout=15)
        assert r3.status_code == 200
        assert (r3.json()["items"][0].get("unread_count") or 0) == 0

        # cache for later tests
        seed_channel_and_lead["channel_id"] = ch_id

    def test_bad_hmac_rejected(self, admin, app_secret):
        if not app_secret:
            pytest.skip("app_secret unavailable")
        payload = _inbound_payload("911234567890", "should_fail")
        raw = json.dumps(payload).encode()
        r = requests.post(f"{BASE_URL}/api/webhooks/whatsapp", data=raw,
                          headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"},
                          timeout=15)
        assert r.status_code == 401


# ============================================================
# WA — message search & starred / pin / react
# ============================================================
class TestMessageActions:
    def test_search_star_pin_react(self, admin, app_secret, seed_channel_and_lead):
        if not app_secret or "channel_id" not in seed_channel_and_lead:
            pytest.skip("Pre-req: unread lifecycle inbound didn't seed channel")
        ch_id = seed_channel_and_lead["channel_id"]
        unique = uuid.uuid4().hex[:8]
        # Seed a unique inbound message to search for
        digits_full = seed_channel_and_lead["digits_full"]
        payload = _inbound_payload(digits_full, f"needle_{unique} content")
        raw = json.dumps(payload).encode()
        rr = requests.post(f"{BASE_URL}/api/webhooks/whatsapp", data=raw,
                           headers={"X-Hub-Signature-256": _sign(app_secret, raw), "Content-Type": "application/json"},
                           timeout=20)
        assert rr.status_code == 200

        # search
        s = admin.get(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/messages?search=needle_{unique}", timeout=15)
        assert s.status_code == 200
        items = s.json()["items"]
        assert items and any(f"needle_{unique}" in (m.get("body") or "") for m in items)
        target = [m for m in items if f"needle_{unique}" in (m.get("body") or "")][0]
        mid = target["id"]

        # star toggle
        r1 = admin.post(f"{BASE_URL}/api/whatsapp/messages/{mid}/star", timeout=15)
        assert r1.status_code == 200 and r1.json()["starred"] is True
        # starred=true filter returns it
        r_starred = admin.get(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/messages?starred=true", timeout=15)
        assert r_starred.status_code == 200
        assert any(m["id"] == mid for m in r_starred.json()["items"])
        # toggle off
        r1b = admin.post(f"{BASE_URL}/api/whatsapp/messages/{mid}/star", timeout=15)
        assert r1b.json()["starred"] is False

        # pin toggle
        r2 = admin.post(f"{BASE_URL}/api/whatsapp/messages/{mid}/pin", timeout=15)
        assert r2.status_code == 200 and r2.json()["pinned"] is True

        # react
        r3 = admin.post(f"{BASE_URL}/api/whatsapp/messages/{mid}/react", json={"emoji": "👍"}, timeout=15)
        assert r3.status_code == 200 and r3.json()["reaction"] == "👍"
        # verify persisted via list
        r_list = admin.get(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/messages?search=needle_{unique}", timeout=15)
        found = [m for m in r_list.json()["items"] if m["id"] == mid][0]
        assert found.get("reaction") == "👍"
        assert found.get("pinned") is True


# ============================================================
# WA — Interested category tags lead + advances stage
# ============================================================
class TestInterestedCategory:
    def test_set_interested_tags_lead(self, admin, app_secret, seed_channel_and_lead):
        if not app_secret or "channel_id" not in seed_channel_and_lead:
            pytest.skip("Pre-req: inbound didn't seed channel")
        ch_id = seed_channel_and_lead["channel_id"]
        lead_id = seed_channel_and_lead["lead_id"]

        r = admin.post(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/category",
                       json={"category": "interested"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["category"] == "interested"

        # verify lead updated: tag "Interested" + lead_stage=Contacted
        lg = admin.get(f"{BASE_URL}/api/leads/{lead_id}", timeout=15)
        assert lg.status_code == 200
        lead = lg.json()
        assert lead.get("lead_stage") == "Contacted", f"lead_stage={lead.get('lead_stage')}"
        # tags is a list of ids; resolve via /api/catalogs
        tag_ids = lead.get("tags") or []
        cr = admin.get(f"{BASE_URL}/api/catalogs", timeout=15).json()
        by_id = {t["id"]: t.get("name") for t in (cr.get("tag") or [])}
        tag_names = [by_id.get(t) if isinstance(t, int) else (t.get("name") if isinstance(t, dict) else str(t)) for t in tag_ids]
        assert any((n or "").lower() == "interested" for n in tag_names), f"Interested tag not on lead; tags={tag_names} ids={tag_ids}"

    def test_unset_category(self, admin, seed_channel_and_lead):
        if "channel_id" not in seed_channel_and_lead:
            pytest.skip("no channel")
        ch_id = seed_channel_and_lead["channel_id"]
        r = admin.post(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/category",
                       json={"category": None}, timeout=15)
        assert r.status_code == 200
        assert r.json()["category"] is None


# ============================================================
# WA — send with reply_to snippet
# ============================================================
class TestSendReply:
    def test_send_with_reply_snippet(self, admin, app_secret, seed_channel_and_lead):
        if not app_secret or "channel_id" not in seed_channel_and_lead:
            pytest.skip("no channel")
        ch_id = seed_channel_and_lead["channel_id"]
        # Get a recent inbound message id to reply to
        mm = admin.get(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/messages?limit=20", timeout=15).json()["items"]
        assert mm, "no messages in channel"
        target = mm[-1]
        target_id = target["id"]

        r = admin.post(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/send",
                       json={"body": f"{TEST_PREFIX} reply-out {uuid.uuid4().hex[:6]}", "reply_to": target_id},
                       timeout=30)
        # Accept 200 (sent/pending) OR 400 (Meta rejected free-text >24h — that's a valid outcome)
        assert r.status_code in (200, 400), r.text
        if r.status_code == 200:
            j = r.json()
            assert j.get("reply_to") and (j["reply_to"].get("body") or "") != ""


# ============================================================
# WA — media upload & serve auth
# ============================================================
class TestMediaUpload:
    def test_media_upload_and_serve_auth(self, admin):
        # Upload
        content = b"iter33-test-bytes-" + uuid.uuid4().hex.encode()
        files = {"file": ("iter33.txt", io.BytesIO(content), "text/plain")}
        r = admin.post(f"{BASE_URL}/api/whatsapp/media/upload", files=files, timeout=30)
        if r.status_code == 502:
            pytest.skip("Object storage not available in preview (502 as documented)")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert j["storage_path"].startswith("homeivf/wa/") or "/wa/" in j["storage_path"]
        assert j["media_url"].startswith("/api/whatsapp/media?path=")
        path = j["storage_path"]

        # 401 without token
        r_noauth = requests.get(f"{BASE_URL}/api/whatsapp/media?path={path}", timeout=15)
        assert r_noauth.status_code == 401

        # 200 with token via auth query param
        r_ok = requests.get(f"{BASE_URL}/api/whatsapp/media?path={path}&auth={admin.token}", timeout=15)
        assert r_ok.status_code == 200
        assert r_ok.content == content


# ============================================================
# WA — inbound reaction webhook
# ============================================================
class TestInboundReactionWebhook:
    def test_reaction_attaches_no_chat_line(self, admin, app_secret, seed_channel_and_lead):
        if not app_secret or "channel_id" not in seed_channel_and_lead:
            pytest.skip("no channel")
        ch_id = seed_channel_and_lead["channel_id"]
        digits_full = seed_channel_and_lead["digits_full"]

        # Send an outbound so we have a wamid to react to; if Meta send fails, seed via inbound with wamid.
        wamid = f"wamid.SEED_{uuid.uuid4().hex[:12]}"
        p = _inbound_payload(digits_full, f"{TEST_PREFIX} target msg", wamid=wamid)
        raw = json.dumps(p).encode()
        rr = requests.post(f"{BASE_URL}/api/webhooks/whatsapp", data=raw,
                           headers={"X-Hub-Signature-256": _sign(app_secret, raw), "Content-Type": "application/json"},
                           timeout=15)
        assert rr.status_code == 200

        # Count messages before
        before = admin.get(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/messages?limit=200", timeout=15).json()["total"]

        # Send reaction webhook
        rp = _reaction_payload(digits_full, wamid, "❤️")
        raw2 = json.dumps(rp).encode()
        rx = requests.post(f"{BASE_URL}/api/webhooks/whatsapp", data=raw2,
                           headers={"X-Hub-Signature-256": _sign(app_secret, raw2), "Content-Type": "application/json"},
                           timeout=15)
        assert rx.status_code == 200

        # No new chat line
        after = admin.get(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/messages?limit=200", timeout=15).json()
        assert after["total"] == before, f"reaction created a chat line ({before} -> {after['total']})"
        # emoji applied on target
        target_msg = [m for m in after["items"] if m.get("wamid") == wamid]
        assert target_msg and target_msg[0].get("reaction") == "❤️"

    def test_reaction_bad_hmac_401(self, app_secret):
        if not app_secret:
            pytest.skip("no app_secret")
        rp = _reaction_payload("911234567890", "wamid.doesnotexist", "🎉")
        raw = json.dumps(rp).encode()
        r = requests.post(f"{BASE_URL}/api/webhooks/whatsapp", data=raw,
                          headers={"X-Hub-Signature-256": "sha256=bad", "Content-Type": "application/json"},
                          timeout=15)
        assert r.status_code == 401
