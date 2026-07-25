"""Iteration 80 backend tests.

Focus:
1. /api/version deploy marker: build tag, leads_index_count=16, indexes_consolidated=True,
   list_sort_field=create_dt, same_day_merge=True.
2. Count fix — GET /api/leads?scope=all total must resolve to real number (~120022),
   not stay -1. Poll a few times because background count may return -1 first.
3. group_counts (lead_stage, source_lead, user_id) fast and non-empty (now IXSCAN via
   re-added {active:1}).
4. Ozonetel CDR endpoint (public): incoming missed call from a NEW number responds fast
   (<3s) and auto-creates a call lead; repeat CDR with same ucid updates the same
   call_event (no duplicate). Even with automations, response is fast (fire-and-forget).
5. Regression: admin login, default /api/leads, sorts, filters, buckets (pipeline,
   ozonetel), caller scoping, dashboard, kpi-overview.
6. SAME-DAY MERGE: webhook creates lead first time, merged on 2nd same-day post with
   same phone, new lead for different phone.
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

# ------------- auth helpers -------------

def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token")
    assert tok, f"no access_token in login response"
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def caller11_token():
    return _login(*CALLER11)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


# ------------- 1. /api/version deploy marker -------------
class TestVersion:
    def test_version_ok(self):
        r = requests.get(f"{BASE_URL}/api/version", timeout=15)
        assert r.status_code == 200, r.text[:200]
        j = r.json()
        assert j.get("build") == "2026-06-db-consolidation+same-day-merge", j
        assert j.get("list_sort_field") == "create_dt", j
        assert j.get("same_day_merge") is True, j
        assert j.get("indexes_consolidated") is True, j
        # The review explicitly says leads_index_count == 16.
        assert j.get("leads_index_count") == 16, f"expected 16 indexes, got {j.get('leads_index_count')} ({j})"


# ------------- 2. Count fix: scope=all -> real total, not -1 -------------
class TestScopeAllTotal:
    def test_scope_all_total_resolves(self, admin_token):
        last_total = None
        # poll up to 5x, sleeping between so the background count can finish
        for i in range(5):
            r = requests.get(f"{BASE_URL}/api/leads?scope=all&limit=20",
                             headers=_hdr(admin_token), timeout=30)
            assert r.status_code == 200, f"scope=all failed: {r.status_code} {r.text[:200]}"
            j = r.json()
            last_total = j.get("total")
            if isinstance(last_total, int) and last_total > 1000:
                break
            time.sleep(2.5)
        assert isinstance(last_total, int) and last_total > 1000, (
            f"scope=all total never resolved to real number after 5 polls, last={last_total}")
        # Sanity: production says ~120022 — allow a wide band.
        assert 50_000 < last_total < 500_000, f"total out of expected range: {last_total}"


# ------------- 3. group_counts fast & non-empty (now IXSCAN) -------------
class TestGroupCounts:
    @pytest.mark.parametrize("group_by", ["lead_stage", "source_lead", "user_id"])
    def test_group_counts_returns_fast(self, admin_token, group_by):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads/group_counts?group_by={group_by}",
                         headers=_hdr(admin_token), timeout=30)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"{group_by} -> {r.status_code} {r.text[:200]}"
        j = r.json()
        # Response should be dict/list-like with counts
        assert j is not None
        # Should be non-empty for these standard groupings
        if isinstance(j, dict):
            data = j.get("counts") or j.get("items") or j.get("groups") or j
        else:
            data = j
        assert data, f"{group_by} returned empty: {j}"
        assert elapsed < 15, f"{group_by} too slow: {elapsed:.2f}s"


# ------------- 4. Ozonetel CDR endpoint -------------
CDR_CLEANUP_PHONES = []      # digits to cleanup
CDR_CLEANUP_UCIDS = []       # ucids to cleanup


def _random_phone():
    # Prefix 9188 + 8 unique digits; avoid collisions with real data
    tail = uuid.uuid4().hex[:6]
    # convert hex chars to digits by mod
    digs = "".join(str(int(c, 16) % 10) for c in tail)
    return f"91887{digs}0"  # 12 digits


class TestOzonetelCDR:
    def test_new_incoming_missed_creates_lead_fast(self):
        phone = _random_phone()
        ucid = f"QA-UCID-{uuid.uuid4().hex[:10]}"
        CDR_CLEANUP_PHONES.append(phone)
        CDR_CLEANUP_UCIDS.append(ucid)
        payload = {
            "CallerID": phone,
            "ucid": ucid,
            "Status": "NotAnswered",
            "CallDuration": "0",
            "CampaignName": "inbound",
        }
        t0 = time.time()
        r = requests.post(f"{BASE_URL}/api/calls/ozonetel/cdr",
                          data={"data": json.dumps(payload)}, timeout=15)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"CDR failed: {r.status_code} {r.text[:200]}"
        assert elapsed < 6, f"CDR too slow: {elapsed:.2f}s (should be well under 3s, allow 6s buffer)"
        j = r.json()
        assert j.get("ok") is True, j
        assert j.get("status") == "missed", j
        assert j.get("lead_id"), f"CDR did not create/return a lead_id: {j}"

    def test_repeat_same_ucid_updates_no_duplicate_call(self, admin_token):
        # Use same ucid + phone as previous test — we'll create fresh here to be robust.
        phone = _random_phone()
        ucid = f"QA-UCID-{uuid.uuid4().hex[:10]}"
        CDR_CLEANUP_PHONES.append(phone)
        CDR_CLEANUP_UCIDS.append(ucid)
        body1 = {"CallerID": phone, "ucid": ucid, "Status": "NotAnswered",
                 "CallDuration": "0", "CampaignName": "inbound"}
        r1 = requests.post(f"{BASE_URL}/api/calls/ozonetel/cdr",
                           data={"data": json.dumps(body1)}, timeout=15)
        assert r1.status_code == 200
        j1 = r1.json()
        call_id_1 = j1.get("call_id")
        lead_id_1 = j1.get("lead_id")
        assert call_id_1 and lead_id_1

        # Second CDR — same ucid, this time "answered" with duration 15s
        body2 = {"CallerID": phone, "ucid": ucid, "Status": "Answered",
                 "CallDuration": "15", "CampaignName": "inbound"}
        t0 = time.time()
        r2 = requests.post(f"{BASE_URL}/api/calls/ozonetel/cdr",
                           data={"data": json.dumps(body2)}, timeout=15)
        elapsed = time.time() - t0
        assert r2.status_code == 200
        assert elapsed < 6, f"repeat CDR too slow: {elapsed:.2f}s"
        j2 = r2.json()
        # Same ucid must resolve to same call_event id
        assert j2.get("call_id") == call_id_1, (
            f"repeat CDR created a new call_event: {call_id_1} vs {j2.get('call_id')}")
        # Same lead
        assert j2.get("lead_id") == lead_id_1

    def test_created_lead_is_active_ozonetel_call_lead(self, admin_token):
        phone = _random_phone()
        ucid = f"QA-UCID-{uuid.uuid4().hex[:10]}"
        CDR_CLEANUP_PHONES.append(phone)
        CDR_CLEANUP_UCIDS.append(ucid)
        body = {"CallerID": phone, "ucid": ucid, "Status": "NotAnswered",
                "CallDuration": "0", "CampaignName": "inbound"}
        r = requests.post(f"{BASE_URL}/api/calls/ozonetel/cdr",
                          data={"data": json.dumps(body)}, timeout=15)
        assert r.status_code == 200
        lead_id = r.json().get("lead_id")
        assert lead_id

        # Verify via admin API
        rl = requests.get(f"{BASE_URL}/api/leads/{lead_id}",
                          headers=_hdr(admin_token), timeout=15)
        assert rl.status_code == 200, rl.text[:200]
        lead = rl.json()
        # Should be an ozonetel call lead
        assert lead.get("ozonetel_lead") is True, f"lead not marked ozonetel: {lead}"
        assert lead.get("pipeline") is False, f"call lead should have pipeline=false: {lead.get('pipeline')}"
        assert lead.get("active", True) is not False, "call lead should be active"


# ------------- 5. Regression: leads endpoints & dashboards -------------
class TestRegression:
    def test_default_leads_list(self, admin_token):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads?limit=20",
                         headers=_hdr(admin_token), timeout=30)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        j = r.json()
        items = j.get("items") or j.get("leads") or []
        assert isinstance(items, list) and len(items) > 0, f"no items: {j}"
        assert elapsed < 20, f"default list too slow: {elapsed:.2f}s"

    @pytest.mark.parametrize("sort", [
        "create_date", "-create_date", "lead_stage", "user_id", "follow_up_date"
    ])
    def test_sorts(self, admin_token, sort):
        r = requests.get(f"{BASE_URL}/api/leads?limit=20&sort={sort}",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, f"sort {sort}: {r.status_code} {r.text[:200]}"

    def test_filter_lead_stage(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=20&lead_stage=Contacted",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200

    def test_filter_date_range(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=20&date_from=2025-01-01&date_to=2026-12-31",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200

    @pytest.mark.parametrize("fu", ["today", "overdue", "upcoming"])
    def test_follow_up_filters(self, admin_token, fu):
        r = requests.get(f"{BASE_URL}/api/leads?limit=20&follow_up={fu}",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200

    def test_search_by_phone(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=5&search=9188",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200

    def test_bucket_pipeline_default(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=10&bucket=pipeline",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200

    def test_bucket_ozonetel(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=10&bucket=ozonetel",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200

    def test_caller_default_scope_own(self, caller11_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=20",
                         headers=_hdr(caller11_token), timeout=30)
        assert r.status_code == 200
        items = r.json().get("items") or []
        # caller default should either be their own leads or a scoped subset
        assert isinstance(items, list)

    def test_dashboard_admin(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/reports/dashboard",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200

    def test_dashboard_caller(self, caller11_token):
        r = requests.get(f"{BASE_URL}/api/reports/dashboard",
                         headers=_hdr(caller11_token), timeout=30)
        assert r.status_code == 200

    def test_kpi_overview(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/reports/kpi-overview",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200


# ------------- 6. Same-day merge regression -------------
_MERGE_STATE = {"webhook_id": None, "token": None, "lead_ids": []}


class TestSameDayMerge:
    def test_create_webhook(self, admin_token):
        name = f"TEST_iter80_{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{BASE_URL}/api/webhooks",
                          headers=_hdr(admin_token),
                          json={"name": name, "source_default": "website",
                                "assign_round_robin": False}, timeout=30)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}"
        j = r.json()
        _MERGE_STATE["webhook_id"] = j.get("id") or j.get("_id")
        _MERGE_STATE["token"] = j.get("token") or j.get("webhook_token")
        assert _MERGE_STATE["webhook_id"] and _MERGE_STATE["token"], f"webhook resp: {j}"

    def test_first_post_creates(self, admin_token):
        assert _MERGE_STATE["token"]
        phone = _random_phone()
        _MERGE_STATE["phoneA"] = phone
        r = requests.post(f"{BASE_URL}/api/webhook/lead/{_MERGE_STATE['token']}",
                          json={"phone": phone, "name": "TEST iter80 A"}, timeout=30)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}"
        j = r.json()
        lead_id = j.get("lead_id") or j.get("id")
        assert lead_id, j
        _MERGE_STATE["leadA"] = lead_id
        _MERGE_STATE["lead_ids"].append(lead_id)
        assert not j.get("merged_same_day"), f"first post shouldn't be merged: {j}"

    def test_second_same_phone_merges(self):
        assert _MERGE_STATE.get("leadA")
        r = requests.post(f"{BASE_URL}/api/webhook/lead/{_MERGE_STATE['token']}",
                          json={"phone": _MERGE_STATE["phoneA"], "name": "TEST iter80 A2"},
                          timeout=30)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}"
        j = r.json()
        assert j.get("merged_same_day") is True, f"expected merged_same_day: {j}"
        assert (j.get("merged_into") == _MERGE_STATE["leadA"]) or (
            j.get("lead_id") == _MERGE_STATE["leadA"]), j

    def test_different_phone_creates_new(self, admin_token):
        phone_b = _random_phone()
        r = requests.post(f"{BASE_URL}/api/webhook/lead/{_MERGE_STATE['token']}",
                          json={"phone": phone_b, "name": "TEST iter80 B"}, timeout=30)
        assert r.status_code in (200, 201)
        j = r.json()
        lead_id = j.get("lead_id") or j.get("id")
        assert lead_id and lead_id != _MERGE_STATE["leadA"], j
        _MERGE_STATE["lead_ids"].append(lead_id)
        assert not j.get("merged_same_day")


# ------------- Cleanup -------------
@pytest.fixture(scope="module", autouse=True)
def _cleanup(request):
    yield
    try:
        tok = _login(*ADMIN)
        h = _hdr(tok)

        # Clean up webhook + its leads
        for lid in _MERGE_STATE.get("lead_ids", []):
            try:
                requests.delete(f"{BASE_URL}/api/leads/{lid}", headers=h, timeout=15)
            except Exception:
                pass
        wid = _MERGE_STATE.get("webhook_id")
        if wid:
            try:
                requests.delete(f"{BASE_URL}/api/webhooks/{wid}", headers=h, timeout=15)
            except Exception:
                pass

        # Clean up Ozonetel test leads (search by phone)
        for phone in CDR_CLEANUP_PHONES:
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
        print(f"cleanup error (non-fatal): {e}")
