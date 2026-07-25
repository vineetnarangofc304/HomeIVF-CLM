"""Iteration 75 — WhatsApp read-endpoint hardening verification.

Verifies:
  - GET /api/whatsapp/channels (admin: default/unread/interested/search/pagination)
  - GET /api/whatsapp/channels/{id}/messages (pagination, search, oldest->newest ordering)
  - GET /api/whatsapp/unread-summary (shape)
  - Caller scoping: caller sees only own channels
  - Regression: /api/calls/active, /api/leads/followups/reminders still 200
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER = {"email": "caller16@homeivf.com", "password": "TestPass@2026"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in login response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login(ADMIN)}"}


@pytest.fixture(scope="module")
def caller_headers():
    return {"Authorization": f"Bearer {_login(CALLER)}"}


@pytest.fixture(scope="module")
def caller_id(caller_headers):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=caller_headers, timeout=10)
    assert r.status_code == 200
    return r.json().get("id")


# ---------- /api/whatsapp/channels (admin) ----------

@pytest.mark.parametrize("params,label", [
    ({}, "default"),
    ({"filter": "unread"}, "unread"),
    ({"filter": "interested"}, "interested"),
    ({"page": 1, "limit": 30}, "page1"),
    ({"page": 2, "limit": 30}, "page2"),
])
def test_admin_channels_variants(admin_headers, params, label):
    t = time.time()
    r = requests.get(f"{BASE_URL}/api/whatsapp/channels", headers=admin_headers, params=params, timeout=15)
    dt = time.time() - t
    assert r.status_code == 200, f"{label}: {r.status_code} {r.text[:200]}"
    body = r.json()
    for k in ("items", "total", "page", "limit"):
        assert k in body, f"{label}: missing key {k}"
    assert isinstance(body["items"], list)
    assert isinstance(body["total"], int)  # -1 allowed on count timeout
    assert dt < 10.0, f"{label}: took {dt:.2f}s (should fail-fast within 5s)"


def test_admin_channels_search(admin_headers):
    # search by digits (returns 200 whether or not there's a match)
    r = requests.get(f"{BASE_URL}/api/whatsapp/channels",
                     headers=admin_headers, params={"search": "9999"}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("items"), list)


# ---------- /api/whatsapp/channels/{id}/messages ----------

def test_channel_messages_flow(admin_headers):
    r = requests.get(f"{BASE_URL}/api/whatsapp/channels", headers=admin_headers,
                     params={"limit": 5}, timeout=15)
    assert r.status_code == 200
    items = r.json().get("items") or []
    if not items:
        pytest.skip("No channels in preview to test messages endpoint")
    ch_id = items[0]["id"]

    # page 1
    r1 = requests.get(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/messages",
                      headers=admin_headers, params={"page": 1, "limit": 20}, timeout=15)
    assert r1.status_code == 200, r1.text[:200]
    b1 = r1.json()
    for k in ("items", "total", "page", "limit"):
        assert k in b1
    msgs = b1["items"]
    assert isinstance(msgs, list)
    # oldest -> newest (list.reverse() applied after DESC sort)
    if len(msgs) >= 2:
        dates = [m.get("date") for m in msgs if m.get("date")]
        assert dates == sorted(dates), f"messages not oldest->newest: {dates[:3]}...{dates[-3:]}"

    # page 2
    r2 = requests.get(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/messages",
                      headers=admin_headers, params={"page": 2, "limit": 20}, timeout=15)
    assert r2.status_code == 200

    # search
    r3 = requests.get(f"{BASE_URL}/api/whatsapp/channels/{ch_id}/messages",
                      headers=admin_headers, params={"search": "hello"}, timeout=15)
    assert r3.status_code == 200
    assert isinstance(r3.json().get("items"), list)


# ---------- /api/whatsapp/unread-summary ----------

def test_unread_summary_admin(admin_headers):
    r = requests.get(f"{BASE_URL}/api/whatsapp/unread-summary", headers=admin_headers, timeout=10)
    assert r.status_code == 200
    b = r.json()
    for k in ("total_unread", "unread_chats", "recent"):
        assert k in b
    assert isinstance(b["recent"], list)
    assert isinstance(b["total_unread"], int)
    assert isinstance(b["unread_chats"], int)


def test_unread_summary_caller(caller_headers):
    r = requests.get(f"{BASE_URL}/api/whatsapp/unread-summary", headers=caller_headers, timeout=10)
    assert r.status_code == 200


# ---------- Caller scoping ----------

def test_caller_channels_scoped_to_own(caller_headers, caller_id):
    r = requests.get(f"{BASE_URL}/api/whatsapp/channels", headers=caller_headers,
                     params={"limit": 100}, timeout=15)
    assert r.status_code == 200
    items = r.json().get("items") or []
    # Every returned channel must belong to caller (owner_id == caller_id) OR list is empty
    bad = [c for c in items if c.get("owner_id") not in (caller_id, None) and c.get("owner_id") != caller_id]
    # strict check: owner_id must equal caller_id
    strict_bad = [c for c in items if c.get("owner_id") != caller_id]
    assert not strict_bad, f"caller saw {len(strict_bad)} channels not owned by them: sample={strict_bad[:2]}"


def test_admin_sees_more_than_caller(admin_headers, caller_headers):
    ra = requests.get(f"{BASE_URL}/api/whatsapp/channels", headers=admin_headers,
                      params={"limit": 1}, timeout=15)
    rc = requests.get(f"{BASE_URL}/api/whatsapp/channels", headers=caller_headers,
                      params={"limit": 1}, timeout=15)
    assert ra.status_code == 200 and rc.status_code == 200
    ta, tc = ra.json().get("total"), rc.json().get("total")
    # allow total=-1 (count timeout) — just assert both endpoints worked
    if isinstance(ta, int) and isinstance(tc, int) and ta >= 0 and tc >= 0:
        assert ta >= tc, f"admin total ({ta}) must be >= caller total ({tc})"


# ---------- Regression: hot pollers ----------

def test_calls_active_regression(admin_headers):
    r = requests.get(f"{BASE_URL}/api/calls/active", headers=admin_headers, timeout=10)
    assert r.status_code == 200


def test_followup_reminders_regression(admin_headers):
    r = requests.get(f"{BASE_URL}/api/leads/followups/reminders", headers=admin_headers, timeout=10)
    assert r.status_code == 200
