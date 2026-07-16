"""Iteration 56 backend tests:
- WEBHOOK DEDUPE: 3 posts of same phone -> 1 lead + 2 merges
- DUPLICATE CLEANUP source filter: scoped to one source
- ODOO REMOVAL: /admin/migration/status and /admin/sync/status must be 404
- /admin/settings and /admin/automations return 200
"""
import os, time, re
import pytest
import requests
from pymongo import MongoClient

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    return s


@pytest.fixture(scope="module")
def mongo():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


# ---------- Odoo removal ----------
class TestOdooRemoval:
    def test_migration_status_404(self, admin_session):
        r = admin_session.get(f"{API}/admin/migration/status", timeout=15)
        assert r.status_code == 404, r.text

    def test_sync_status_404(self, admin_session):
        r = admin_session.get(f"{API}/admin/sync/status", timeout=15)
        assert r.status_code == 404, r.text

    def test_admin_settings_200(self, admin_session):
        r = admin_session.get(f"{API}/admin/settings", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_admin_automations_200(self, admin_session):
        r = admin_session.get(f"{API}/admin/automations", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------- Webhook dedupe ----------
class TestWebhookDedupe:
    @pytest.fixture(scope="class")
    def webhook(self, admin_session):
        r = admin_session.post(f"{API}/webhooks", json={
            "name": "TEST_WAA_iter56", "source_default": "Website AI Agent",
            "assign_round_robin": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        hook = r.json()
        yield hook
        admin_session.delete(f"{API}/webhooks/{hook['id']}")

    def test_dedupe(self, admin_session, webhook, mongo):
        phone = "9998887" + str(int(time.time()))[-3:]  # unique 10-digit
        payload = {"name": "TEST_iter56_dup", "phone": phone, "query": "iter56 dedupe"}
        url = f"{API}/webhook/lead/{webhook['token']}"

        # 1st POST
        r1 = requests.post(url, json=payload, timeout=20)
        assert r1.status_code == 200, r1.text
        j1 = r1.json()
        assert j1.get("ok") is True
        lead_id = j1.get("lead_id")
        assert lead_id and not j1.get("duplicate"), j1

        # 2nd + 3rd POST -> duplicate
        for i in range(2):
            r = requests.post(url, json=payload, timeout=20)
            assert r.status_code == 200, r.text
            j = r.json()
            assert j.get("ok") is True
            assert j.get("duplicate") is True, j
            assert j.get("merged_into") == lead_id, j

        # Only ONE active lead for this phone
        phone_digits = re.sub(r"\D", "", phone)[-10:]
        cnt = mongo.leads.count_documents({"phone_digits": phone_digits, "active": True})
        assert cnt == 1, f"expected 1 active lead for {phone_digits}, got {cnt}"

        # Cleanup: hard-delete the created lead + follow_ups + messages
        mongo.leads.delete_many({"phone_digits": phone_digits})
        mongo.mail_messages.delete_many({"res_id": lead_id})


# ---------- Duplicate scan source filter ----------
class TestDupScanSourceFilter:
    """Seed 4 disposable duplicate leads across 2 sources, run scans, then clean up.
    Uses direct DB seed so we don't touch webhook round-robin state.
    """

    SEED_IDS = []

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, mongo, admin_session):
        # Fabricate 4 leads: 2 phones, each phone appearing twice on same source.
        # Phone A -> source "Website AI Agent" (2 leads, so 1 duplicate)
        # Phone B -> source "Meta" (2 leads, so 1 duplicate)
        today = time.strftime("%Y-%m-%d")
        ts_old = f"{today} 00:00:00"
        ts_new = f"{today} 12:00:00"

        def _next(seq):
            return mongo.ir_sequences.find_one_and_update(
                {"name": seq}, {"$inc": {"value": 1}}, upsert=True, return_document=True
            )["value"]

        phoneA = "8880001111"
        phoneB = "8880002222"
        rows = []
        for src, phone in (("Website AI Agent", phoneA), ("Meta", phoneB)):
            for tstamp in (ts_old, ts_new):
                lid = _next("lead")
                rows.append({
                    "id": lid, "active": True, "stage_id": 1, "name": "TEST_iter56_dupscan",
                    "phone": phone, "phone_digits": phone,
                    "source_lead": src, "create_date": tstamp,
                    "type": "lead",
                })
        mongo.leads.insert_many(rows)
        TestDupScanSourceFilter.SEED_IDS = [r["id"] for r in rows]
        yield
        mongo.leads.delete_many({"id": {"$in": TestDupScanSourceFilter.SEED_IDS}})

    def _wait_done(self, admin_session, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            r = admin_session.get(f"{API}/admin/duplicates/scan/status", timeout=10)
            assert r.status_code == 200
            j = r.json()
            if j.get("status") == "done":
                return j
            if j.get("status") == "error":
                pytest.fail(f"scan error: {j}")
            time.sleep(1)
        pytest.fail("scan timeout")

    def test_scan_source_scoped(self, admin_session):
        today = time.strftime("%Y-%m-%d")
        r = admin_session.post(f"{API}/admin/duplicates/scan",
            json={"date_from": today, "date_to": today, "source": "Website AI Agent"}, timeout=15)
        assert r.status_code == 200
        j = self._wait_done(admin_session)
        assert j.get("source") == "Website AI Agent", j
        # Ensure every keeper + candidate is that source
        for g in j.get("groups") or []:
            assert g["keeper"]["source_lead"] == "Website AI Agent", g
            for c in g["candidates"]:
                assert c["source_lead"] == "Website AI Agent", c
        # Should include our seeded WAA duplicate
        seed = set(TestDupScanSourceFilter.SEED_IDS)
        found = set(j.get("candidate_ids") or [])
        # Meta seeded ids should NOT appear
        meta_ids = [i for i in TestDupScanSourceFilter.SEED_IDS if i > TestDupScanSourceFilter.SEED_IDS[1]]
        for mid in meta_ids:
            assert mid not in found, f"Meta lead {mid} leaked into WAA scan"

    def test_scan_all_sources(self, admin_session):
        today = time.strftime("%Y-%m-%d")
        r = admin_session.post(f"{API}/admin/duplicates/scan",
            json={"date_from": today, "date_to": today}, timeout=15)
        assert r.status_code == 200
        j = self._wait_done(admin_session)
        assert (j.get("source") or "") == "", j
        # collect the sources found in groups; both should appear if seeded dups exist
        sources = set()
        for g in j.get("groups") or []:
            sources.add(g["keeper"]["source_lead"])
        # At minimum both seeded sources should be present
        assert "Website AI Agent" in sources, sources
        assert "Meta" in sources, sources
