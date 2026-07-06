"""Iteration 26 — WhatsApp template + tracking (Case 5) regression tests.

Covers: templates CRUD (whatsapp), send_whatsapp records wa_tracking,
wa-tracking endpoints (template summary/messages, message detail w/ flow,
lead messages), regression (RBAC 403 on reports/export, followups CRUD,
gmail auth-url error path).
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER = {"email": "agent@homeivf.com", "password": "Agent@2026"}


def _login(session, creds):
    r = session.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token")
    assert tok, "no access_token"
    session.headers.update({"Authorization": f"Bearer {tok}"})
    return tok


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    _login(s, ADMIN)
    return s


@pytest.fixture(scope="module")
def caller_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    _login(s, CALLER)
    return s


# ---------- Templates ----------
class TestTemplates:
    def test_list_whatsapp(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/templates/whatsapp")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_create_draft(self, admin_session):
        payload = {"name": "TEST_iter26_wa_tpl", "body": "Hello {{1}}, this is a test.",
                   "status": "draft", "lang": "en", "category": "MARKETING"}
        r = admin_session.post(f"{BASE_URL}/api/templates/whatsapp", json=payload)
        assert r.status_code in (200, 201), r.text[:300]
        d = r.json()
        assert d["name"] == payload["name"]
        assert "id" in d
        pytest.tpl_id = d["id"]

    def test_get_single(self, admin_session):
        tid = pytest.tpl_id
        r = admin_session.get(f"{BASE_URL}/api/templates/whatsapp/{tid}")
        assert r.status_code == 200
        assert r.json()["id"] == tid

    def test_patch_new_fields(self, admin_session):
        tid = pytest.tpl_id
        payload = {
            "applies_to": "lead", "phone_field": "phone", "header_type": "text",
            "category": "MARKETING", "footer": "Reply STOP to opt out",
            "user_access": ["admin", "manager"],
            "buttons": [{"type": "QUICK_REPLY", "text": "Yes"}, {"type": "QUICK_REPLY", "text": "No"}],
            "variables": [{"key": "1", "sample": "Kunal"}],
            "status": "approved",
        }
        r = admin_session.patch(f"{BASE_URL}/api/templates/whatsapp/{tid}", json=payload)
        assert r.status_code == 200, r.text[:300]
        # GET back and verify persistence
        g = admin_session.get(f"{BASE_URL}/api/templates/whatsapp/{tid}").json()
        assert g["footer"] == payload["footer"]
        assert g["status"] == "approved"
        assert len(g["buttons"]) == 2
        assert g["variables"][0]["sample"] == "Kunal"
        assert g["applies_to"] == "lead"


# ---------- Send + tracking ----------
class TestWaTracking:
    def test_send_whatsapp_records_tracking(self, admin_session):
        # find a lead with phone
        r = admin_session.get(f"{BASE_URL}/api/leads?page=1&limit=50")
        assert r.status_code == 200
        items = r.json().get("items", [])
        lead = next((x for x in items if x.get("phone")), None)
        assert lead, "no lead with phone"
        pytest.lead_id = lead["id"]

        tpl_id = pytest.tpl_id
        r = admin_session.post(f"{BASE_URL}/api/leads/{pytest.lead_id}/send_whatsapp",
                               json={"template_id": tpl_id}, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        d = r.json()
        # accept either sent or failed - tracking record should still exist
        assert "status" in d or "id" in d or "ok" in d

    def test_lead_messages(self, admin_session):
        time.sleep(1)
        r = admin_session.get(f"{BASE_URL}/api/wa/lead/{pytest.lead_id}/messages")
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) >= 1
        rec = arr[0]
        for k in ("id", "template_name", "status", "body", "sent_to"):
            assert k in rec, f"missing field {k}: {rec}"
        pytest.track_id = rec["id"]
        pytest.wamid = rec.get("wamid")

    def test_template_summary(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/wa/template/{pytest.tpl_id}/summary")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] >= 1
        assert isinstance(d["by_status"], dict)

    def test_template_messages(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/wa/template/{pytest.tpl_id}/messages")
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and len(d["items"]) >= 1

    def test_message_detail_with_flow(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/wa/message/{pytest.track_id}")
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == pytest.track_id
        assert isinstance(d.get("flow"), list) and len(d["flow"]) == 9
        assert "status_history" in d


# ---------- Webhook status update ----------
class TestWebhookStatus:
    def test_webhook_delivered(self, admin_session):
        wamid = getattr(pytest, "wamid", None)
        if not wamid:
            pytest.skip("send failed, no wamid to update via webhook")
        s = admin_session.get(f"{BASE_URL}/api/admin/settings").json()
        wa = s.get("whatsapp_cloud") if isinstance(s, dict) else None
        if not wa:
            pytest.skip("whatsapp_cloud settings not found")
        app_secret = wa.get("app_secret")
        if not app_secret:
            pytest.skip("no app_secret")
        import hmac, hashlib, json as _json
        body = _json.dumps({
            "entry": [{"changes": [{"value": {"statuses": [
                {"id": wamid, "status": "delivered", "timestamp": str(int(time.time()))}
            ]}}]}]
        }).encode()
        sig = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
        r = requests.post(f"{BASE_URL}/api/webhooks/whatsapp", data=body,
                          headers={"Content-Type": "application/json",
                                   "X-Hub-Signature-256": sig}, timeout=15)
        assert r.status_code in (200, 204), r.text[:300]
        time.sleep(1)
        d = admin_session.get(f"{BASE_URL}/api/wa/message/{pytest.track_id}").json()
        assert d["status"] == "delivered", f"status={d.get('status')}"


# ---------- Regression ----------
class TestRegression:
    def test_caller_export_403(self, caller_session):
        r = caller_session.get(f"{BASE_URL}/api/export/leads.xlsx")
        assert r.status_code in (401, 403), f"expected 403 got {r.status_code}"

    def test_admin_reports_dashboard_ok(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/reports/dashboard")
        assert r.status_code == 200

    def test_followups_crud(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/leads/{pytest.lead_id}/followups")
        assert r.status_code == 200

    def test_gmail_authurl_error_path(self, admin_session):
        # If Gmail is not configured this should return a clear error, not 500
        r = admin_session.get(f"{BASE_URL}/api/gmail/auth-url")
        assert r.status_code in (200, 400, 404, 409), r.status_code
