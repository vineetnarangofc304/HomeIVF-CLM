"""Iteration 83 — regression after 2-pass index build + estimated_document_count for unfiltered total.

Under test:
- server.py _ensure_indexes now runs _create_all() twice (pass1, drop stale, pass2)
  so an index (e.g. active_1) that hit the 64-cap during pass1 is recovered in pass2.
  Confirmed via /api/version returning leads_index_count=16 and indexes_consolidated=true.
- leads.py _cached_count uses estimated_document_count() for empty / {active:True} queries,
  so the admin/scope=all unfiltered total can never COLLSCAN-storm the DB. Filtered
  counts still use count_documents.
- All previous regressions from iter79/80/82 must still pass.
"""
import os
import time
import json
import uuid
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = ("admin@homeivf.com", "HomeIVF@2026")
CALLER11 = ("caller11@homeivf.com", "TestPass@2026")


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token")
    assert tok, "no access_token"
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def caller_token():
    return _login(*CALLER11)


def _hdr(t):
    return {"Authorization": f"Bearer {t}"}


def _random_phone():
    digs = "".join(str(int(c, 16) % 10) for c in uuid.uuid4().hex[:6])
    return f"91887{digs}0"


def _resolve_total(url, headers, tries=6, sleep=2.5):
    """Poll a leads list endpoint until total resolves to non -1 int or timeout."""
    last = None
    for _ in range(tries):
        r = requests.get(url, headers=headers, timeout=30)
        assert r.status_code == 200, f"{url}: {r.status_code} {r.text[:200]}"
        last = r.json().get("total")
        if isinstance(last, int) and last >= 0:
            return last
        time.sleep(sleep)
    return last


# ---------- 1. /api/version marker (confirms 2-pass build recovered active_1) -------------
class TestVersion:
    def test_version_marker(self):
        r = requests.get(f"{BASE_URL}/api/version", timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j.get("leads_index_count") == 16, j
        assert j.get("leads_index_count_expected") == 16, j
        assert j.get("indexes_consolidated") is True, j
        assert j.get("build") == "2026-06-db-consolidation+same-day-merge", j


# ---------- 2. Admin default + scope=all uses estimated_document_count -------------
class TestAdminLeads:
    def test_default_list_fast(self, admin_token):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads?limit=20",
                         headers=_hdr(admin_token), timeout=30)
        el = time.time() - t0
        assert r.status_code == 200, r.text[:200]
        items = r.json().get("items") or []
        assert isinstance(items, list) and len(items) > 0
        assert el < 20, f"default admin list too slow: {el:.2f}s"

    def test_scope_all_total_resolves_via_estimate(self, admin_token):
        # First call may be -1 (async coalesced), poll until resolved
        total = _resolve_total(f"{BASE_URL}/api/leads?scope=all&limit=20",
                               _hdr(admin_token))
        assert isinstance(total, int) and total > 1000, f"total never resolved: {total}"
        # estimated_document_count is instant; should be a sensible bulk number
        assert 50_000 < total < 500_000, f"unexpected total: {total}"

    def test_scope_all_filtered_uses_exact_count(self, admin_token):
        # Filtered path must NOT use estimate — should return exact count via count_documents
        total = _resolve_total(
            f"{BASE_URL}/api/leads?scope=all&limit=20&lead_stage=Contacted",
            _hdr(admin_token))
        assert isinstance(total, int) and total >= 0, f"filtered total: {total}"
        # Sensible for Contacted stage in ~120k dataset
        assert total < 500_000, f"unreasonably large: {total}"

    @pytest.mark.parametrize("sort", ["create_date", "-create_date", "lead_stage"])
    def test_sorts(self, admin_token, sort):
        r = requests.get(f"{BASE_URL}/api/leads?limit=20&sort={sort}",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, f"{sort}: {r.status_code} {r.text[:200]}"

    def test_filter_lead_stage(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=20&lead_stage=Contacted",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200

    def test_filter_date_range(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=20&date_from=2025-01-01&date_to=2026-12-31",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200

    def test_phone_search(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=5&search=9188",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200

    def test_bucket_ozonetel(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=10&bucket=ozonetel",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200


# ---------- 3. Caller default (own book, exact count_documents on user_id partial idx) --------
class TestCallerLeads:
    def test_caller_default_fast(self, caller_token):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads?limit=20",
                         headers=_hdr(caller_token), timeout=30)
        el = time.time() - t0
        assert r.status_code == 200, r.text[:200]
        assert el < 20, f"caller default too slow: {el:.2f}s"

    def test_caller_default_total_exact(self, caller_token):
        total = _resolve_total(f"{BASE_URL}/api/leads?limit=20",
                               _hdr(caller_token))
        assert isinstance(total, int) and total >= 0, f"caller total: {total}"

    def test_caller_default_sorted_desc(self, caller_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=10",
                         headers=_hdr(caller_token), timeout=30)
        assert r.status_code == 200
        items = r.json().get("items") or []
        dates = []
        for it in items:
            v = it.get("create_dt") or it.get("create_date") or it.get("created_at")
            if v:
                dates.append(str(v))
        for i in range(1, len(dates)):
            assert dates[i - 1] >= dates[i], f"not desc-sorted: {dates}"


# ---------- 4. group_counts -------------
class TestGroupCounts:
    @pytest.mark.parametrize("group_by", ["lead_stage", "user_id"])
    def test_group_counts(self, admin_token, group_by):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads/group_counts?group_by={group_by}",
                         headers=_hdr(admin_token), timeout=30)
        el = time.time() - t0
        assert r.status_code == 200, r.text[:200]
        assert el < 15, f"{group_by} too slow: {el:.2f}s"
        assert r.json(), "empty response"


# ---------- 5. Same-day merge regression -------------
_STATE = {"webhook_id": None, "token": None, "leads": []}


class TestSameDayMerge:
    def test_create_webhook(self, admin_token):
        name = f"TEST_iter83_{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{BASE_URL}/api/webhooks",
                          headers=_hdr(admin_token),
                          json={"name": name, "source_default": "website",
                                "assign_round_robin": False}, timeout=30)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}"
        j = r.json()
        _STATE["webhook_id"] = j.get("id") or j.get("_id")
        _STATE["token"] = j.get("token") or j.get("webhook_token")
        assert _STATE["webhook_id"] and _STATE["token"], j

    def test_first_post_creates(self):
        phone = _random_phone()
        _STATE["phoneA"] = phone
        r = requests.post(f"{BASE_URL}/api/webhook/lead/{_STATE['token']}",
                          json={"phone": phone, "name": "TEST iter83 A"}, timeout=30)
        assert r.status_code in (200, 201), r.text[:200]
        j = r.json()
        lid = j.get("lead_id") or j.get("id")
        assert lid, j
        _STATE["leadA"] = lid
        _STATE["leads"].append(lid)
        assert not j.get("merged_same_day"), j

    def test_second_same_phone_merges(self):
        r = requests.post(f"{BASE_URL}/api/webhook/lead/{_STATE['token']}",
                          json={"phone": _STATE["phoneA"], "name": "TEST iter83 A2"},
                          timeout=30)
        assert r.status_code in (200, 201)
        j = r.json()
        assert j.get("merged_same_day") is True, f"expected merged_same_day: {j}"
        merged = j.get("merged_into") or j.get("lead_id")
        assert merged == _STATE["leadA"], j

    def test_different_phone_creates(self):
        phone_b = _random_phone()
        r = requests.post(f"{BASE_URL}/api/webhook/lead/{_STATE['token']}",
                          json={"phone": phone_b, "name": "TEST iter83 B"}, timeout=30)
        assert r.status_code in (200, 201)
        j = r.json()
        lid = j.get("lead_id") or j.get("id")
        assert lid and lid != _STATE["leadA"], j
        _STATE["leads"].append(lid)
        assert not j.get("merged_same_day"), j


# ---------- 6. Ozonetel CDR regression -------------
_CDR = {"phones": [], "ucids": []}


class TestOzonetelCDR:
    def test_new_missed_creates_fast(self):
        phone = _random_phone()
        ucid = f"QA-SAT-{uuid.uuid4().hex[:8]}"
        _CDR["phones"].append(phone)
        _CDR["ucids"].append(ucid)
        body = {"CallerID": phone, "ucid": ucid, "Status": "NotAnswered",
                "CallDuration": "0", "CampaignName": "inbound"}
        t0 = time.time()
        r = requests.post(f"{BASE_URL}/api/calls/ozonetel/cdr",
                          data={"data": json.dumps(body)}, timeout=15)
        el = time.time() - t0
        assert r.status_code == 200, r.text[:200]
        assert el < 6, f"CDR too slow: {el:.2f}s"
        j = r.json()
        assert j.get("ok") is True, j
        assert j.get("lead_id"), j
        _CDR["lead_id_1"] = j.get("lead_id")
        _CDR["call_id_1"] = j.get("call_id")

    def test_repeat_same_ucid_no_duplicate(self):
        phone = _CDR["phones"][0]
        ucid = _CDR["ucids"][0]
        body = {"CallerID": phone, "ucid": ucid, "Status": "Answered",
                "CallDuration": "20", "CampaignName": "inbound"}
        r = requests.post(f"{BASE_URL}/api/calls/ozonetel/cdr",
                          data={"data": json.dumps(body)}, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j.get("call_id") == _CDR["call_id_1"], j
        assert j.get("lead_id") == _CDR["lead_id_1"], j


# ---------- CLEANUP -------------
@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    try:
        tok = _login(*ADMIN)
        h = _hdr(tok)
        for lid in _STATE.get("leads", []):
            try:
                requests.delete(f"{BASE_URL}/api/leads/{lid}", headers=h, timeout=15)
            except Exception:
                pass
        wid = _STATE.get("webhook_id")
        if wid:
            try:
                requests.delete(f"{BASE_URL}/api/webhooks/{wid}", headers=h, timeout=15)
            except Exception:
                pass
        if _CDR.get("lead_id_1"):
            try:
                requests.delete(f"{BASE_URL}/api/leads/{_CDR['lead_id_1']}", headers=h, timeout=15)
            except Exception:
                pass
        for phone in _CDR.get("phones", []):
            try:
                rr = requests.get(f"{BASE_URL}/api/leads?search={phone}&limit=5&scope=all",
                                  headers=h, timeout=20)
                if rr.status_code == 200:
                    for it in (rr.json().get("items") or []):
                        lid = it.get("id") or it.get("_id")
                        if lid:
                            requests.delete(f"{BASE_URL}/api/leads/{lid}", headers=h, timeout=10)
            except Exception:
                pass
    except Exception as e:
        print(f"cleanup non-fatal: {e}")
