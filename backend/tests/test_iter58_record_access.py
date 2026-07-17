"""Iteration 58 tests — record-level access control + duplicate/my-leads filters.
CASE 1: callers can view any lead, edit only own; CASE 2: duplicate & my-leads filters."""
import os
import requests
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/") + "/api"
ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER = {"email": "agent@homeivf.com", "password": "Agent@2026"}
CALLER_ID = 1001
FOREIGN_LEAD = 133223  # owned by user 2


def _login(creds):
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def admin():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def caller():
    return _login(CALLER)


@pytest.fixture(scope="module")
def foreign_lead(admin):
    # Ensure #133223 is NOT assigned to caller 1001 for the denial tests
    r = admin.get(f"{BASE}/leads/{FOREIGN_LEAD}", timeout=30)
    assert r.status_code == 200, r.text
    if r.json().get("user_id") == CALLER_ID:
        admin.patch(f"{BASE}/leads/{FOREIGN_LEAD}", json={"updates": {"user_id": 2}}, timeout=30)
    return FOREIGN_LEAD


# ---- CASE 1a: caller sees ALL leads (list is not owner-scoped) ----
def test_caller_list_is_not_owner_scoped(caller):
    r = caller.get(f"{BASE}/leads", params={"limit": 1}, timeout=60)
    assert r.status_code == 200
    total = r.json().get("total", 0)
    # More than a caller's own share — DB has ~120k leads
    assert total > 50000, f"caller should see all leads, got total={total}"


def test_caller_can_view_foreign_lead(caller, foreign_lead):
    r = caller.get(f"{BASE}/leads/{foreign_lead}", timeout=30)
    assert r.status_code == 200
    assert r.json()["id"] == foreign_lead
    assert r.json().get("user_id") != CALLER_ID  # confirm foreign


# ---- CASE 1b: every mutation on foreign lead → 403 Access Denied ----
DENIED_ENDPOINTS = [
    ("PATCH", "/leads/{id}", {"updates": {"city": "X"}}),
    ("POST", "/leads/{id}/lost", {"note": "x"}),
    ("POST", "/leads/{id}/promote-to-pipeline", {}),
    ("POST", "/leads/{id}/send_whatsapp", {"template_id": 1}),
    ("POST", "/leads/{id}/send_email", {"subject": "s", "body": "b"}),
    ("POST", "/leads/{id}/followups", {"note": "x", "follow_up_date": "2026-01-30"}),
    ("POST", "/leads/{id}/caller-activities", {"feedback": "x"}),
    ("POST", "/leads/{id}/messages", {"body": "note", "subtype": "note"}),
]


@pytest.mark.parametrize("method,path,body", DENIED_ENDPOINTS)
def test_caller_denied_on_foreign_lead(caller, foreign_lead, method, path, body):
    url = f"{BASE}{path.format(id=foreign_lead)}"
    r = caller.request(method, url, json=body, timeout=30)
    assert r.status_code == 403, f"{method} {path} expected 403, got {r.status_code}: {r.text}"
    assert "Access Denied" in r.text, f"detail should contain 'Access Denied': {r.text}"


def test_caller_denied_on_dial_foreign(caller, foreign_lead):
    r = caller.post(f"{BASE}/calls/dial", json={"lead_id": foreign_lead}, timeout=30)
    # 403 must fire BEFORE the Ozonetel config check (400)
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"
    assert "Access Denied" in r.text


# ---- CASE 1c: after admin assigns lead to caller, caller CAN edit ----
def test_caller_can_edit_after_assignment(admin, caller, foreign_lead):
    # Assign to caller
    r = admin.patch(f"{BASE}/leads/{foreign_lead}", json={"updates": {"user_id": CALLER_ID}}, timeout=30)
    assert r.status_code == 200
    try:
        # PATCH city
        r = caller.patch(f"{BASE}/leads/{foreign_lead}", json={"updates": {"city": "TestCity58"}}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("city") == "TestCity58"
        # Verify persisted via GET
        r = caller.get(f"{BASE}/leads/{foreign_lead}", timeout=30)
        assert r.json().get("city") == "TestCity58"
        # caller-activity
        r = caller.post(f"{BASE}/leads/{foreign_lead}/caller-activities",
                        json={"feedback": "TEST_iter58 activity"}, timeout=30)
        assert r.status_code == 200, r.text
        # followup with note
        r = caller.post(f"{BASE}/leads/{foreign_lead}/followups",
                        json={"note": "TEST_iter58 fu", "follow_up_date": "2026-02-05"}, timeout=30)
        assert r.status_code == 200, r.text
    finally:
        # Revert owner to user 2 as instructed
        admin.patch(f"{BASE}/leads/{foreign_lead}", json={"updates": {"user_id": 2}}, timeout=30)


# ---- CASE 1d: admin has no ownership restriction ----
def test_admin_can_edit_any_lead(admin, foreign_lead):
    r = admin.patch(f"{BASE}/leads/{foreign_lead}", json={"updates": {"priority": "1"}}, timeout=30)
    assert r.status_code == 200


# ---- CASE 2: duplicate=true filter ----
def test_duplicate_filter_returns_only_duplicates(admin):
    r = admin.get(f"{BASE}/leads", params={"duplicate": "true", "limit": 50}, timeout=60)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1, f"expected exactly 1 duplicate, got {data['total']}"
    for it in data["items"]:
        assert it.get("is_duplicate") is True


def test_duplicate_filter_ignores_active(admin):
    # Even active=false or active=true — duplicate=true should surface it regardless
    r = admin.get(f"{BASE}/leads", params={"duplicate": "true", "active": "true", "limit": 5}, timeout=60)
    assert r.status_code == 200
    assert r.json()["total"] == 1


# ---- Regression: caller sees all leads even with duplicate filter ----
def test_caller_can_see_duplicate_filter(caller):
    r = caller.get(f"{BASE}/leads", params={"duplicate": "true", "limit": 5}, timeout=60)
    assert r.status_code == 200
    assert r.json()["total"] == 1
