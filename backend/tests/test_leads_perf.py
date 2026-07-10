"""Backend perf & correctness tests for GET /api/leads after adding compound indexes."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to reading frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER = {"email": "agent@homeivf.com", "password": "Agent@2026"}

MAX_SECONDS = 8.0  # generous threshold for 120k docs on preview infra


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"Login failed for {creds['email']}: {r.status_code} {r.text[:200]}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in login response: {data}"
    return token


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login(ADMIN)}"}


@pytest.fixture(scope="module")
def caller_headers():
    return {"Authorization": f"Bearer {_login(CALLER)}"}


def _get(headers, params):
    t0 = time.time()
    r = requests.get(f"{BASE_URL}/api/leads", headers=headers, params=params, timeout=30)
    elapsed = time.time() - t0
    return r, elapsed


# --- Default listing (index-covered) ---
def test_admin_default_page1(admin_headers):
    r, elapsed = _get(admin_headers, {"page": 1, "limit": 50})
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    assert elapsed < MAX_SECONDS, f"Default page took {elapsed:.2f}s"
    # total should reflect seeded 120k (plus any originals)
    total = data.get("total") or data.get("total_count") or data.get("count")
    items = data.get("items") or data.get("leads") or data.get("data") or []
    assert total is not None and total >= 120000, f"Expected >=120000 total, got {total}"
    assert len(items) == 50, f"Expected 50 items, got {len(items)}"
    # verify default sort create_date desc
    dates = [it.get("create_date") for it in items if it.get("create_date")]
    assert dates == sorted(dates, reverse=True), "Not sorted create_date desc"
    print(f"admin default page1: total={total}, len={len(items)}, {elapsed:.2f}s")


def test_admin_pagination(admin_headers):
    r1, e1 = _get(admin_headers, {"page": 2, "limit": 50})
    r2, e2 = _get(admin_headers, {"page": 3, "limit": 50})
    assert r1.status_code == 200 and r2.status_code == 200
    assert e1 < MAX_SECONDS and e2 < MAX_SECONDS
    items1 = r1.json().get("items") or r1.json().get("leads") or []
    items2 = r2.json().get("items") or r2.json().get("leads") or []
    ids1 = {it.get("id") for it in items1}
    ids2 = {it.get("id") for it in items2}
    assert ids1 and ids2 and ids1.isdisjoint(ids2), "Pages overlap"
    print(f"pagination p2 {e1:.2f}s p3 {e2:.2f}s")


# --- Filters ---
@pytest.mark.parametrize("params", [
    {"source_lead": "Website"},
    {"lead_stage": "Contacted"},
    {"search": "Lead"},
])
def test_admin_filters(admin_headers, params):
    params = {**params, "page": 1, "limit": 50}
    r, elapsed = _get(admin_headers, params)
    assert r.status_code == 200, f"{params} -> {r.status_code} {r.text[:200]}"
    assert elapsed < MAX_SECONDS, f"{params} took {elapsed:.2f}s"
    data = r.json()
    items = data.get("items") or data.get("leads") or []
    assert isinstance(items, list)
    print(f"filter {params}: {elapsed:.2f}s items={len(items)}")


# --- Sorting ---
def test_admin_sort_name_asc(admin_headers):
    r, elapsed = _get(admin_headers, {"sort": "name", "order": "asc", "page": 1, "limit": 50})
    assert r.status_code == 200, r.text[:300]
    # not index-covered by design, but must still succeed without 500/timeout
    assert elapsed < 30, f"Sort by name too slow: {elapsed:.2f}s"
    print(f"sort name asc: {elapsed:.2f}s")


def test_admin_sort_createdate_desc(admin_headers):
    r, elapsed = _get(admin_headers, {"sort": "create_date", "order": "desc", "page": 1, "limit": 50})
    assert r.status_code == 200, r.text[:300]
    assert elapsed < MAX_SECONDS, f"sort createdate desc took {elapsed:.2f}s"
    print(f"sort createdate desc: {elapsed:.2f}s")


# --- Caller scoped ---
def test_caller_scoped(caller_headers):
    r, elapsed = _get(caller_headers, {"page": 1, "limit": 50})
    assert r.status_code == 200, r.text[:300]
    assert elapsed < MAX_SECONDS, f"caller listing took {elapsed:.2f}s"
    data = r.json()
    total = data.get("total") or data.get("total_count") or data.get("count") or 0
    assert total < 120000, f"Caller should not see all 120k leads, got total={total}"
    print(f"caller scoped total={total} {elapsed:.2f}s")
