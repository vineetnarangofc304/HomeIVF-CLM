"""Regression test suite after MongoDB index optimization (iteration_46).

Verifies Dashboard, Leads list (paginated), Lead detail (followups /
caller-activities / messages), Reports (pivot/trends), and Follow-ups analytics
all return 200 and reasonable payloads. Also captures elapsed timings.
"""
import os
import time

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://homeivf-crm-1.preview.emergentagent.com"
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASSWORD = "HomeIVF@2026"


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token")
    assert tok
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


def _timed(sess, method, path, **kw):
    url = f"{BASE_URL}{path}"
    t0 = time.perf_counter()
    r = sess.request(method, url, timeout=60, **kw)
    dt = time.perf_counter() - t0
    print(f"[{r.status_code}] {method} {path} in {dt:.2f}s")
    return r, dt


def test_health(client):
    r, _ = _timed(client, "GET", "/api/health")
    assert r.status_code == 200


# ---------- Dashboard widgets ----------
def test_dashboard(client):
    r, dt = _timed(client, "GET", "/api/reports/dashboard")
    assert r.status_code == 200
    data = r.json()
    # widget keys — be lenient about exact naming
    assert isinstance(data, dict)
    keys = set(data.keys())
    print("dashboard keys:", keys)
    assert dt < 10, f"dashboard too slow: {dt}s"


def test_followups_analytics(client):
    r, dt = _timed(client, "GET", "/api/leads/followups/analytics")
    assert r.status_code == 200
    assert dt < 10


# ---------- Leads list + pagination ----------
def test_leads_list_page1(client):
    r, dt = _timed(client, "GET", "/api/leads?page=1&limit=25")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    # find items + total in any reasonable shape
    items = body.get("items") or body.get("results") or body.get("leads") or body.get("data")
    assert items is not None, f"no items key: {list(body.keys())}"
    assert isinstance(items, list)
    assert len(items) > 0
    total = body.get("total") or body.get("count") or body.get("total_count")
    print("leads total:", total, "page items:", len(items))
    assert dt < 10
    return items


def test_leads_list_page2(client):
    r, _ = _timed(client, "GET", "/api/leads?page=2&limit=25")
    assert r.status_code == 200
    body = r.json()
    items = body.get("items") or body.get("results") or body.get("leads") or body.get("data") or []
    assert isinstance(items, list)


def test_leads_list_sorted(client):
    r, _ = _timed(client, "GET", "/api/leads?page=1&limit=10&sort=create_date&order=desc")
    assert r.status_code == 200


# ---------- Lead detail sub-sections ----------
@pytest.fixture(scope="session")
def sample_lead_id(client):
    r = client.get(f"{BASE_URL}/api/leads?page=1&limit=1", timeout=30)
    assert r.status_code == 200
    body = r.json()
    items = body.get("items") or body.get("results") or body.get("leads") or body.get("data") or []
    assert items, "no leads to pick"
    lid = items[0].get("id") or items[0].get("_id")
    assert lid, f"no id field on lead: {items[0]}"
    print("sample lead id:", lid)
    return lid


def test_lead_get(client, sample_lead_id):
    r, dt = _timed(client, "GET", f"/api/leads/{sample_lead_id}")
    assert r.status_code == 200
    assert dt < 10


def test_lead_followups(client, sample_lead_id):
    r, dt = _timed(client, "GET", f"/api/leads/{sample_lead_id}/followups")
    assert r.status_code == 200
    assert dt < 10, f"followups slow: {dt}s"


def test_lead_caller_activities(client, sample_lead_id):
    # try both plausible paths
    for p in [f"/api/leads/{sample_lead_id}/caller-activities", f"/api/leads/{sample_lead_id}/caller_activities"]:
        r, dt = _timed(client, "GET", p)
        if r.status_code == 200:
            assert dt < 10
            return
    pytest.fail("caller-activities endpoint not found")


def test_lead_messages(client, sample_lead_id):
    for p in [
        f"/api/chatter/messages?lead_id={sample_lead_id}&page=1&limit=25",
        f"/api/chatter/{sample_lead_id}/messages?page=1&limit=25",
        f"/api/leads/{sample_lead_id}/messages?page=1&limit=25",
    ]:
        r, dt = _timed(client, "GET", p)
        if r.status_code == 200:
            assert dt < 15
            return
    pytest.fail("chatter messages endpoint not found")


# ---------- Reports ----------
def test_pivot_user(client):
    r, dt = _timed(client, "POST", "/api/reports/pivot", json={"rows": ["user_id"], "filters": {}})
    assert r.status_code == 200, r.text[:300]
    assert dt < 15


def test_pivot_source_x_stage(client):
    r, dt = _timed(client, "POST", "/api/reports/pivot",
                   json={"rows": ["source_lead"], "cols": "lead_stage", "filters": {}})
    assert r.status_code == 200, r.text[:300]
    assert dt < 15


def test_trends(client):
    r, dt = _timed(client, "GET", "/api/reports/trends")
    assert r.status_code == 200
    assert dt < 15
