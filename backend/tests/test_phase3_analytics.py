"""Phase 3 — Agent Analytics + Pending Queue + caller role-scoping tests."""
import os
import datetime as dt
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASS = "HomeIVF@2026"
AGENT_EMAIL = "agent@homeivf.com"
AGENT_PASS = "Agent@2026"
TODAY = dt.datetime.utcnow().strftime("%Y-%m-%d")


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    j = r.json()
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {j['access_token']}"})
    return s, j


@pytest.fixture(scope="module")
def admin():
    s, j = _login(ADMIN_EMAIL, ADMIN_PASS)
    return s, j


@pytest.fixture(scope="module")
def agent():
    s, j = _login(AGENT_EMAIL, AGENT_PASS)
    return s, j


# ---- Auth + role ----
def test_agent_login_role_caller(agent):
    _, j = agent
    assert j.get("role") == "caller", f"expected caller, got {j.get('role')}"
    assert j.get("email") == AGENT_EMAIL


def test_admin_login_role_admin(admin):
    _, j = admin
    assert j.get("role") == "admin"


# ---- GET /api/agent/analytics ----
def test_analytics_admin_is_manager_true(admin):
    s, _ = admin
    r = s.get(f"{BASE_URL}/api/agent/analytics?date={TODAY}", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["date"] == TODAY
    assert data["is_manager"] is True
    assert isinstance(data["agents"], list)
    assert "totals" in data
    for k in ("total", "connected", "missed", "outbound", "incoming", "talk_time",
             "conversions", "break_seconds", "connect_rate"):
        assert k in data["totals"], f"missing totals key: {k}"
    # at least one agent with activity should appear (seed data)
    assert len(data["agents"]) >= 1, "expected at least one agent row (seeded data)"
    for a in data["agents"]:
        for k in ("user_id", "name", "total", "connected", "missed", "outbound",
                 "incoming", "avg_duration", "talk_time", "conversions",
                 "break_seconds", "connect_rate"):
            assert k in a, f"missing key {k} in agent row"


def test_analytics_caller_is_manager_false_self_only(agent):
    s, j = agent
    uid = j["id"]
    r = s.get(f"{BASE_URL}/api/agent/analytics?date={TODAY}", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_manager"] is False
    assert isinstance(data["agents"], list)
    # caller must only see their own row (if seeded). Either 0 or 1 row, and if present must be self.
    assert len(data["agents"]) <= 1
    for a in data["agents"]:
        assert a["user_id"] == uid, f"caller saw foreign user_id {a['user_id']}"


def test_analytics_default_date_is_today(admin):
    s, _ = admin
    r = s.get(f"{BASE_URL}/api/agent/analytics", timeout=30)
    assert r.status_code == 200
    assert r.json()["date"] == TODAY


def test_analytics_unauth_401():
    r = requests.get(f"{BASE_URL}/api/agent/analytics", timeout=30)
    assert r.status_code in (401, 403)


# ---- Role enforcement on manager-only endpoints ----
def test_caller_blocked_from_live(agent):
    s, _ = agent
    r = s.get(f"{BASE_URL}/api/agent/live", timeout=30)
    assert r.status_code == 403, f"expected 403 for caller on /agent/live, got {r.status_code} {r.text}"


def test_caller_blocked_from_status_logs(agent):
    s, _ = agent
    r = s.get(f"{BASE_URL}/api/agent/status-logs", timeout=30)
    assert r.status_code == 403


def test_admin_allowed_on_live(admin):
    s, _ = admin
    r = s.get(f"{BASE_URL}/api/agent/live", timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---- Pending Queue: GET /api/calls?status=queued ----
def test_pending_queue_admin_status_queued(admin):
    s, _ = admin
    r = s.get(f"{BASE_URL}/api/calls?status=queued&limit=50", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "items" in data and "total" in data
    for it in data["items"]:
        assert it.get("status") == "queued", f"unexpected status {it.get('status')}"


def test_pending_queue_caller_self_only(agent):
    s, j = agent
    uid = j["id"]
    r = s.get(f"{BASE_URL}/api/calls?status=queued&limit=50", timeout=30)
    assert r.status_code == 200
    data = r.json()
    for it in data["items"]:
        assert it.get("status") == "queued"
        assert it.get("user_id") == uid, f"caller saw call belonging to user_id {it.get('user_id')}"
