"""
Iteration 67 tests: caller default list re-scoped to own book.
- Default caller GET /api/leads -> own book (~5144)
- ?scope=all -> all leads (~119813)
- Search is global, spans buckets
- ?user_id=<colleague_id> -> colleague book
- Admin default -> all leads
- original_user_id locked; PATCH strips user_id/original_user_id for callers
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
API = f"{BASE_URL}/api"

ADMIN = ("admin@homeivf.com", "HomeIVF@2026")
HIMANI = ("caller16@homeivf.com", "TestPass@2026")  # id 8
ANAMIKA = ("caller11@homeivf.com", "TestPass@2026")  # id 5

TEST_LEAD_ID = 600027
SEARCH_PHONE = "5770614172"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def himani_h():
    return _login(*HIMANI)


@pytest.fixture(scope="module")
def anamika_h():
    return _login(*ANAMIKA)


@pytest.fixture(scope="module")
def admin_h():
    return _login(*ADMIN)


def _get(path, headers, params=None, timeout=30):
    t0 = time.time()
    r = requests.get(f"{API}{path}", headers=headers, params=params, timeout=timeout)
    dt = time.time() - t0
    return r, dt


# --- Case 1: caller default scoped to own book ---
def test_caller_default_scoped_own_book(himani_h):
    r, dt = _get("/leads", himani_h, params={"limit": 50})
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    total = data.get("total", data.get("count"))
    assert total is not None
    # ~5144 for Himani
    assert 4000 <= total <= 7000, f"expected Himani own book ~5144, got {total}"
    items = data.get("items") or data.get("leads") or []
    assert items, "expected items"
    # every item owned by user_id 8
    owners = {i.get("user_id") for i in items}
    assert owners == {8}, f"expected all user_id=8, got {owners}"
    assert dt < 5.0, f"caller default too slow: {dt:.2f}s"


def test_caller_scope_all_returns_all(himani_h):
    r, dt = _get("/leads", himani_h, params={"scope": "all", "limit": 50})
    assert r.status_code == 200, r.text[:300]
    total = r.json().get("total")
    assert total and total > 100000, f"expected ~119813 with scope=all, got {total}"


def test_caller_search_global_spans_buckets(himani_h):
    # search on default pipeline tab should still find raw ozonetel lead
    r, _ = _get("/leads", himani_h, params={"search": SEARCH_PHONE, "bucket": "pipeline"})
    assert r.status_code == 200, r.text[:300]
    items = r.json().get("items") or r.json().get("leads") or []
    ids = [i.get("id") or i.get("lead_id") for i in items]
    assert TEST_LEAD_ID in ids, f"expected lead {TEST_LEAD_ID} in search results, got {ids[:10]}"
    lead = next(i for i in items if (i.get("id") or i.get("lead_id")) == TEST_LEAD_ID)
    assert lead.get("user_id") == 5


def test_caller_colleague_filter(himani_h):
    r, _ = _get("/leads", himani_h, params={"user_id": 5, "limit": 20})
    assert r.status_code == 200, r.text[:300]
    total = r.json().get("total")
    assert 3000 <= total <= 8000, f"expected Anamika book ~5073, got {total}"
    items = r.json().get("items") or r.json().get("leads") or []
    owners = {i.get("user_id") for i in items}
    assert owners == {5}, f"expected all user_id=5, got {owners}"


def test_admin_default_all_leads(admin_h):
    r, _ = _get("/leads", admin_h, params={"limit": 20})
    assert r.status_code == 200
    total = r.json().get("total")
    assert total > 100000, f"expected admin sees all ~119813, got {total}"


def test_group_counts_fast(himani_h):
    r, dt = _get("/leads/group_counts", himani_h)
    assert r.status_code == 200
    assert dt < 3.0, f"group_counts slow: {dt:.2f}s"


# --- Case 2: lock + strip ---
def test_original_user_id_locked_and_stripped(himani_h):
    # Fetch first
    r = requests.get(f"{API}/leads/{TEST_LEAD_ID}", headers=himani_h, timeout=30)
    assert r.status_code == 200, r.text[:300]
    before = r.json()
    assert before.get("user_id") == 5
    assert before.get("original_user_id") == 5

    # Attempt to change user_id + original_user_id + a benign field
    r = requests.patch(
        f"{API}/leads/{TEST_LEAD_ID}",
        headers=himani_h,
        json={"updates": {"user_id": 8, "original_user_id": 8, "city": "Jaipur-QA67"}},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:300]

    # Verify persistence
    r = requests.get(f"{API}/leads/{TEST_LEAD_ID}", headers=himani_h, timeout=30)
    after = r.json()
    assert after.get("user_id") == 5, f"user_id changed! now {after.get('user_id')}"
    assert after.get("original_user_id") == 5, f"original_user_id changed! now {after.get('original_user_id')}"
    assert after.get("city") == "Jaipur-QA67", f"city not persisted: {after.get('city')}"


def test_audit_log_shows_edit_by_himani(himani_h):
    # Try common audit endpoints
    for path in (f"/leads/{TEST_LEAD_ID}/audit", f"/leads/{TEST_LEAD_ID}/activity", f"/audit/leads/{TEST_LEAD_ID}"):
        r = requests.get(f"{API}{path}", headers=himani_h, timeout=30)
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else (data.get("items") or data.get("audit") or [])
            texts = str(items).lower()
            assert "himani" in texts or "user_id\": 8" in texts or "'user_id': 8" in texts, \
                f"expected Himani in audit at {path}: {texts[:400]}"
            return
    pytest.skip("no audit endpoint reachable")
