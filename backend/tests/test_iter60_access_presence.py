"""
Iteration 60 — Test suite for:
  CASE 1: caller can edit any lead + original_user_id lock + Activity Log audit
  CASE 2: Agent status, presence-based routing / queue drain, attendance API
Cleans up all created leads / audit_logs / lead_queue entries. Resets caller status to Offline.
"""
import os
import time
import uuid
import requests
import pytest

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = ("admin@homeivf.com", "HomeIVF@2026")
CALLER = ("agent@homeivf.com", "Agent@2026")
CALLER_ID = 1001


def _login(email, pw):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def admin():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def caller():
    return _login(*CALLER)


@pytest.fixture(scope="module")
def webhook_token(admin):
    r = admin.get(f"{BASE}/api/webhooks", timeout=15)
    assert r.status_code == 200
    for w in r.json():
        if "HomeIVF Website" in (w.get("name") or ""):
            return w["token"]
    return r.json()[0]["token"]


@pytest.fixture(scope="module", autouse=True)
def _reset_caller_offline_end(admin, caller):
    yield
    try:
        caller.post(f"{BASE}/api/agent/status", json={"status": "Offline"}, timeout=15)
    except Exception:
        pass


# ----------------- CASE 1: audit endpoint & edit as caller -----------------

class TestCase1Audit:
    def test_admin_audit_endpoint_shape(self, admin):
        leads = admin.get(f"{BASE}/api/leads?limit=1", timeout=20).json()
        items = leads.get("items") or leads if isinstance(leads, list) else leads.get("items")
        assert items, "no leads"
        lid = items[0]["id"]
        r = admin.get(f"{BASE}/api/leads/{lid}/audit", timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_caller_can_edit_any_lead_and_audit_recorded(self, admin, caller):
        # find a lead NOT assigned to CALLER_ID
        leads = admin.get(f"{BASE}/api/leads?limit=50", timeout=20).json()
        items = leads.get("items") if isinstance(leads, dict) else leads
        target = next((l for l in items if l.get("user_id") != CALLER_ID), None)
        assert target, "no non-caller lead found"
        lid = target["id"]
        new_city = f"TEST_CITY_{uuid.uuid4().hex[:6]}"
        r = caller.patch(f"{BASE}/api/leads/{lid}", json={"updates": {"city": new_city}}, timeout=20)
        assert r.status_code == 200, f"caller edit blocked: {r.status_code} {r.text}"
        # verify
        got = caller.get(f"{BASE}/api/leads/{lid}", timeout=20).json()
        assert got.get("city") == new_city
        # audit entry
        aud = admin.get(f"{BASE}/api/leads/{lid}/audit", timeout=20).json()
        assert any(("city" in str(a).lower() and new_city in str(a)) for a in aud), f"no audit row for city change: {aud[:3]}"
        # restore city
        orig = target.get("city") or ""
        admin.patch(f"{BASE}/api/leads/{lid}", json={"updates": {"city": orig}}, timeout=20)

    def test_caller_cannot_reassign(self, caller, admin):
        leads = admin.get(f"{BASE}/api/leads?limit=20", timeout=20).json()
        items = leads.get("items") if isinstance(leads, dict) else leads
        target = items[0]
        lid = target["id"]
        r = caller.patch(f"{BASE}/api/leads/{lid}", json={"updates": {"user_id": CALLER_ID}}, timeout=20)
        # server may 403 or silently strip; verify user_id unchanged
        after = admin.get(f"{BASE}/api/leads/{lid}", timeout=20).json()
        assert after.get("user_id") == target.get("user_id"), f"caller reassigned lead! {after.get('user_id')} vs {target.get('user_id')}"


# ----------------- CASE 2: status, queue drain, attendance -----------------

class TestCase2Presence:
    def test_agent_status_set_and_get(self, caller):
        r = caller.post(f"{BASE}/api/agent/status", json={"status": "Offline"}, timeout=15)
        assert r.status_code == 200
        me = caller.get(f"{BASE}/api/agent/me", timeout=15).json()
        assert me.get("status") == "Offline"

    def test_queue_when_all_offline_then_drain_on_available(self, admin, caller, webhook_token):
        # Ensure caller offline
        caller.post(f"{BASE}/api/agent/status", json={"status": "Offline"}, timeout=15)
        phone = f"9{uuid.uuid4().int % 10**9:09d}"
        payload = {
            "name": f"TEST_QUEUE_{uuid.uuid4().hex[:6]}",
            "phone": phone,
            "email": "test_queue@example.com",
            "assign_round_robin": True,
        }
        r = requests.post(f"{BASE}/api/webhook/lead/{webhook_token}", json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text
        body = r.json()
        lead_id = body.get("lead_id") or body.get("id") or (body.get("lead") or {}).get("id")
        assert lead_id, f"no lead id in {body}"

        # confirm unassigned
        got = admin.get(f"{BASE}/api/leads/{lead_id}", timeout=15).json()
        assert got.get("user_id") in (None, 0), f"expected unassigned, got user_id={got.get('user_id')}"

        # confirm in queue
        q = admin.get(f"{BASE}/api/agent/queue", timeout=15).json()
        q_items = q if isinstance(q, list) else q.get("items", [])
        assert any((it.get("lead_id") == lead_id or it.get("id") == lead_id) for it in q_items), f"lead {lead_id} not in queue: {q_items[:5]}"

        # caller becomes Available → drain
        r2 = caller.post(f"{BASE}/api/agent/status", json={"status": "Available"}, timeout=20)
        assert r2.status_code == 200
        drained = r2.json().get("assigned_from_queue", 0)
        assert drained >= 1, f"expected assigned_from_queue>=1, got {r2.json()}"

        # confirm lead now assigned to caller and original_user_id set
        got2 = admin.get(f"{BASE}/api/leads/{lead_id}", timeout=15).json()
        assert got2.get("user_id") == CALLER_ID, f"lead not assigned to caller: {got2.get('user_id')}"
        assert got2.get("original_user_id") == CALLER_ID, f"original_user_id not set: {got2.get('original_user_id')}"

        # cleanup: reset status Offline and delete lead
        caller.post(f"{BASE}/api/agent/status", json={"status": "Offline"}, timeout=10)
        admin.delete(f"{BASE}/api/leads/{lead_id}", timeout=15)

    def test_direct_assign_when_available(self, admin, caller, webhook_token):
        caller.post(f"{BASE}/api/agent/status", json={"status": "Available"}, timeout=15)
        time.sleep(0.5)
        phone = f"9{uuid.uuid4().int % 10**9:09d}"
        payload = {
            "name": f"TEST_DIRECT_{uuid.uuid4().hex[:6]}",
            "phone": phone,
            "email": "test_direct@example.com",
            "assign_round_robin": True,
        }
        r = requests.post(f"{BASE}/api/webhook/lead/{webhook_token}", json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text
        body = r.json()
        lead_id = body.get("lead_id") or body.get("id") or (body.get("lead") or {}).get("id")
        assert lead_id
        got = admin.get(f"{BASE}/api/leads/{lead_id}", timeout=15).json()
        # Should be assigned directly (to the only available caller = 1001) — but other callers might be available too
        assert got.get("user_id") not in (None, 0), f"lead was queued instead of direct-assigned: {got.get('user_id')}"
        # cleanup
        caller.post(f"{BASE}/api/agent/status", json={"status": "Offline"}, timeout=10)
        admin.delete(f"{BASE}/api/leads/{lead_id}", timeout=15)

    def test_attendance_day(self, admin):
        from datetime import date
        today = date.today().isoformat()
        r = admin.get(f"{BASE}/api/agent/attendance?date={today}", timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        # Expect list of callers or dict with items
        rows = data if isinstance(data, list) else (data.get("items") or data.get("rows") or data.get("attendance") or [])
        assert rows, f"attendance day empty: {data}"

    def test_attendance_month(self, admin):
        from datetime import date
        month = date.today().strftime("%Y-%m")
        r = admin.get(f"{BASE}/api/agent/attendance?month={month}", timeout=30)
        assert r.status_code == 200, r.text
