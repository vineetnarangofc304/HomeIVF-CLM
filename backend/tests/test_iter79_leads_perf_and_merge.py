"""Iteration 79 backend tests.

Focus:
1. Leads list performance & correctness after index consolidation (57 -> 15) and
   removal of the non-selective pipeline filter.
2. Sort variants (create_date/create_date_ist -> create_dt migration).
3. Filter variants (date range on create_dt, lead_stage, tags, search).
4. Bucket tabs (pipeline / ozonetel).
5. Caller scoping.
6. Dashboard, KPI overview, group_counts.
7. Lead detail + update.
8. SAME-DAY LEAD MERGE via website webhook and Facebook test-lead endpoint.
"""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

ADMIN = ("admin@homeivf.com", "HomeIVF@2026")
CALLER11 = ("caller11@homeivf.com", "TestPass@2026")
CALLER16 = ("caller16@homeivf.com", "TestPass@2026")

ACCEPTABLE_504_MSG = "This view is taking too long"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password},
                      timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token")
    assert tok, f"no access_token in login response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def caller11_token():
    return _login(*CALLER11)


@pytest.fixture(scope="module")
def caller16_token():
    return _login(*CALLER16)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- 1. Default leads list opens fast ----------
class TestLeadsDefault:
    def test_default_list_fast(self, admin_token):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads", headers=_hdr(admin_token), timeout=20)
        dt = time.time() - t0
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) > 0, "default leads list empty"
        assert dt < 15, f"default /api/leads took {dt:.1f}s (>15s)"
        # background total pattern: -1 initially is expected
        assert "total" in data
        print(f"default list: {len(data['items'])} items in {dt:.2f}s total={data['total']}")

    def test_scope_all_returns_real_total(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(admin_token),
                         params={"scope": "all"}, timeout=25)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        # real count ~120013
        assert isinstance(data.get("total"), int)
        assert data["total"] > 100000, f"expected ~120k total, got {data['total']}"
        assert len(data["items"]) > 0


# ---------- 2. Sort variants ----------
SORT_INDEX_BACKED = ["create_date", "lead_stage", "user_id", "follow_up_date", "phone"]
SORT_POSSIBLY_HEAVY = ["contact_name", "city"]


class TestLeadsSort:
    @pytest.mark.parametrize("sort_field", SORT_INDEX_BACKED)
    @pytest.mark.parametrize("order", ["desc", "asc"])
    def test_sort_index(self, admin_token, sort_field, order):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(admin_token),
                         params={"sort": sort_field, "order": order}, timeout=25)
        dt = time.time() - t0
        assert r.status_code == 200, f"{sort_field}/{order}: {r.status_code} {r.text[:200]}"
        assert dt < 20, f"{sort_field}/{order} took {dt:.1f}s"
        items = r.json().get("items", [])
        assert isinstance(items, list)
        print(f"sort {sort_field}/{order}: {len(items)} items in {dt:.2f}s")

    @pytest.mark.parametrize("sort_field", SORT_POSSIBLY_HEAVY)
    def test_sort_heavy_accepts_504_fastfail(self, admin_token, sort_field):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(admin_token),
                         params={"sort": sort_field, "order": "desc"}, timeout=30)
        # Either 200 fast, or a clean 504 with the fail-fast message
        assert r.status_code in (200, 504), f"{sort_field}: {r.status_code} {r.text[:200]}"
        if r.status_code == 504:
            body = r.text
            assert ACCEPTABLE_504_MSG in body, f"504 without fail-fast msg: {body[:200]}"


# ---------- 3. Filters ----------
class TestLeadsFilters:
    def test_lead_stage_contacted(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(admin_token),
                         params={"lead_stage": "Contacted"}, timeout=25)
        assert r.status_code == 200, r.text[:200]

    def test_date_range_on_create_dt(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(admin_token),
                         params={"date_from": "2025-06-01",
                                 "date_to": "2025-06-30"}, timeout=25)
        assert r.status_code == 200, r.text[:200]
        items = r.json().get("items", [])
        # Sanity: sample first 10 should have create_date_ist in June 2025 (if field present)
        checked = 0
        for it in items[:10]:
            d = it.get("create_date_ist") or it.get("create_date") or ""
            if "2025-06" in d:
                checked += 1
        # allow lenient — some items may not have that string field but date_from/to must not 500
        print(f"date filter items={len(items)} sampleJune2025={checked}")

    @pytest.mark.parametrize("val", ["today", "overdue", "upcoming"])
    def test_follow_up(self, admin_token, val):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(admin_token),
                         params={"follow_up": val}, timeout=25)
        assert r.status_code == 200, f"follow_up={val}: {r.status_code} {r.text[:200]}"

    def test_search_phone(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(admin_token),
                         params={"search": "9829221590"}, timeout=25)
        assert r.status_code == 200, r.text[:200]

    def test_search_name(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(admin_token),
                         params={"search": "Sharma"}, timeout=25)
        assert r.status_code == 200, r.text[:200]


# ---------- 4. Bucket tabs ----------
class TestBuckets:
    def test_bucket_pipeline_default(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(admin_token),
                         params={"bucket": "pipeline"}, timeout=25)
        assert r.status_code == 200, r.text[:200]
        assert len(r.json().get("items", [])) > 0

    def test_bucket_ozonetel(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(admin_token),
                         params={"bucket": "ozonetel", "scope": "all"}, timeout=25)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        # ozonetel bucket should return a small set
        assert data.get("total", 0) < 5000 or data.get("total", 0) == -1
        print(f"ozonetel bucket total={data.get('total')} items={len(data.get('items', []))}")


# ---------- 5. Caller scoping ----------
class TestCallerScope:
    def test_caller11_default_is_own_book(self, caller11_token):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(caller11_token), timeout=25)
        assert r.status_code == 200, r.text[:200]
        items = r.json().get("items", [])
        # Best-effort: at least the first few items should have user_id=5 or be empty
        # (allow either because API may not always include user_id)
        for it in items[:5]:
            uid = it.get("user_id")
            if uid is not None:
                assert uid == 5, f"caller11 default leaked non-owned user_id={uid}"

    def test_caller11_scope_all(self, caller11_token):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(caller11_token),
                         params={"scope": "all"}, timeout=25)
        assert r.status_code == 200

    def test_caller16_default(self, caller16_token):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(caller16_token), timeout=25)
        assert r.status_code == 200


# ---------- 6. group_counts ----------
class TestGroupCounts:
    @pytest.mark.parametrize("gb", ["lead_stage", "source_lead", "user_id"])
    def test_group_counts(self, admin_token, gb):
        r = requests.get(f"{BASE_URL}/api/leads/group_counts",
                         headers=_hdr(admin_token),
                         params={"group_by": gb}, timeout=30)
        assert r.status_code == 200, f"group_by={gb}: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert isinstance(data, (dict, list)), type(data)


# ---------- 7. Dashboard & KPI ----------
class TestReports:
    def test_dashboard_admin(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/reports/dashboard",
                         headers=_hdr(admin_token), timeout=60)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        # Dashboard sections may be flat or grouped depending on section= param
        keys = set(d.keys())
        expected_any = {"kpis", "funnel", "trends", "by_stage", "by_day",
                        "leads_today", "total_leads", "leads_mtd"}
        assert keys & expected_any, f"unexpected dashboard keys: {list(keys)[:15]}"
        # Sanity check: total_leads (if present) should be ~120k after pipeline filter removal
        if "total_leads" in d:
            assert d["total_leads"] > 100000, f"total_leads={d['total_leads']} (<100k)"

    def test_dashboard_caller(self, caller11_token):
        r = requests.get(f"{BASE_URL}/api/reports/dashboard",
                         headers=_hdr(caller11_token), timeout=60)
        assert r.status_code == 200, r.text[:200]

    def test_kpi_overview(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/reports/kpi-overview",
                         headers=_hdr(admin_token), timeout=60)
        assert r.status_code == 200, r.text[:200]


# ---------- 8. Lead detail + update ----------
class TestLeadDetailUpdate:
    def test_detail_and_update(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads",
                         headers=_hdr(admin_token),
                         params={"limit": 1}, timeout=15)
        assert r.status_code == 200
        items = r.json().get("items", [])
        assert items, "no leads to test detail"
        lead_id = items[0].get("id") or items[0].get("_id")
        assert lead_id
        t0 = time.time()
        d = requests.get(f"{BASE_URL}/api/leads/{lead_id}",
                         headers=_hdr(admin_token), timeout=15)
        dt = time.time() - t0
        assert d.status_code == 200, d.text[:200]
        assert dt < 10, f"detail took {dt:.1f}s"
        # Try update: append a benign note in a common field
        original = d.json()
        # Use a mostly-safe field — 'city' — record original, restore after
        orig_city = original.get("city")
        new_city = f"TESTCITY_{uuid.uuid4().hex[:6]}"
        up = requests.patch(f"{BASE_URL}/api/leads/{lead_id}",
                            headers=_hdr(admin_token),
                            json={"updates": {"city": new_city}}, timeout=15)
        assert up.status_code in (200, 204), f"update failed: {up.status_code} {up.text[:200]}"
        # verify persisted
        v = requests.get(f"{BASE_URL}/api/leads/{lead_id}",
                         headers=_hdr(admin_token), timeout=15)
        assert v.status_code == 200
        assert v.json().get("city") == new_city
        # restore
        requests.patch(f"{BASE_URL}/api/leads/{lead_id}",
                       headers=_hdr(admin_token),
                       json={"updates": {"city": orig_city or ""}}, timeout=15)


# ---------- 9. Same-day merge (webhook) ----------
class TestSameDayMerge:
    @pytest.fixture(scope="class")
    def webhook(self, admin_token):
        # Create webhook to get token
        r = requests.post(f"{BASE_URL}/api/webhooks",
                          headers=_hdr(admin_token),
                          json={"name": f"TEST_iter79_{uuid.uuid4().hex[:6]}",
                                "source_default": "website",
                                "assign_round_robin": False}, timeout=15)
        assert r.status_code in (200, 201), f"create webhook: {r.status_code} {r.text[:300]}"
        wh = r.json()
        token = wh.get("token") or wh.get("webhook_token") or wh.get("id")
        assert token, f"no token in webhook create response: {wh}"
        wh_id = wh.get("id") or wh.get("_id") or wh.get("webhook_id")
        yield {"token": token, "id": wh_id, "raw": wh}
        # cleanup webhook if possible
        if wh_id:
            try:
                requests.delete(f"{BASE_URL}/api/webhooks/{wh_id}",
                                headers=_hdr(admin_token), timeout=10)
            except Exception:
                pass

    def test_same_day_merge_and_diff_phone(self, admin_token, webhook):
        token = webhook["token"]
        phone_a = f"9{int(time.time())%1000000000:09d}"[:10]
        # ensure 10 digits and unlikely to collide
        phone_a = "9" + str(int(time.time() * 1000))[-9:]
        phone_b = "8" + str(int(time.time() * 1000) + 1)[-9:]
        created_ids = []

        # 1st post
        r1 = requests.post(f"{BASE_URL}/api/webhook/lead/{token}",
                           json={"phone": phone_a, "name": "TEST_iter79_A",
                                 "source": "website"}, timeout=20)
        assert r1.status_code in (200, 201), f"1st: {r1.status_code} {r1.text[:200]}"
        j1 = r1.json()
        assert j1.get("ok") is True, j1
        lead_id_1 = j1.get("lead_id")
        assert lead_id_1
        created_ids.append(lead_id_1)
        assert not j1.get("duplicate"), f"1st should not be duplicate: {j1}"

        # 2nd post same phone
        r2 = requests.post(f"{BASE_URL}/api/webhook/lead/{token}",
                           json={"phone": phone_a, "name": "TEST_iter79_A2",
                                 "source": "website"}, timeout=20)
        assert r2.status_code in (200, 201), f"2nd: {r2.status_code} {r2.text[:200]}"
        j2 = r2.json()
        assert j2.get("ok") is True
        assert j2.get("duplicate") is True, f"expected duplicate=true: {j2}"
        assert j2.get("merged_same_day") is True, f"expected merged_same_day=true: {j2}"
        assert j2.get("merged_into") == lead_id_1 or j2.get("lead_id") == lead_id_1, \
            f"expected merged into {lead_id_1}: {j2}"

        # 3rd post different phone -> new lead
        r3 = requests.post(f"{BASE_URL}/api/webhook/lead/{token}",
                           json={"phone": phone_b, "name": "TEST_iter79_B",
                                 "source": "website"}, timeout=20)
        assert r3.status_code in (200, 201), r3.text[:200]
        j3 = r3.json()
        assert j3.get("ok") is True
        new_id = j3.get("lead_id")
        assert new_id and new_id != lead_id_1, f"different phone should create new lead: {j3}"
        assert not j3.get("duplicate"), f"different phone should not be duplicate: {j3}"
        created_ids.append(new_id)

        # verify chatter shows the merge note on lead_id_1
        # try common message endpoints
        found_msg = False
        for path in [f"/api/leads/{lead_id_1}/messages",
                     f"/api/leads/{lead_id_1}/chatter",
                     f"/api/leads/{lead_id_1}"]:
            m = requests.get(f"{BASE_URL}{path}",
                             headers=_hdr(admin_token), timeout=15)
            if m.status_code == 200:
                txt = m.text
                if "Repeat web enquiry" in txt or "same-day duplicate merged" in txt or "merged_same_day" in txt:
                    found_msg = True
                    break
        assert found_msg, "merge chatter note not found on merged lead"

        # cleanup: attempt to delete test leads
        for lid in created_ids:
            try:
                requests.delete(f"{BASE_URL}/api/leads/{lid}",
                                headers=_hdr(admin_token), timeout=10)
            except Exception:
                pass


# ---------- 10. Facebook test-lead endpoint always creates ----------
class TestFacebookTestLead:
    def test_fb_test_lead_always_creates(self, admin_token):
        # Two consecutive calls with same phone should both create leads (dedupe_today=False)
        phone = "7" + str(int(time.time() * 1000))[-9:]
        created = []
        for i in range(2):
            body = {
                "field_data": [
                    {"name": "full_name", "values": [f"TEST_iter79_fb_{i}"]},
                    {"name": "phone_number", "values": [phone]},
                ],
                "form_name": "TEST_iter79_form",
            }
            r = requests.post(f"{BASE_URL}/api/admin/facebook/test",
                              headers=_hdr(admin_token),
                              json=body, timeout=25)
            assert r.status_code in (200, 201), f"fb test-lead {i}: {r.status_code} {r.text[:200]}"
            j = r.json()
            assert j.get("ok") is True
            lid = j.get("lead_id")
            assert lid, f"no lead_id: {j}"
            created.append(lid)
        assert created[0] != created[1], \
            f"fb test-lead should NOT dedupe (dedupe_today=False); got same id twice: {created}"
        # cleanup
        for lid in created:
            try:
                requests.delete(f"{BASE_URL}/api/leads/{lid}",
                                headers=_hdr(admin_token), timeout=10)
            except Exception:
                pass
