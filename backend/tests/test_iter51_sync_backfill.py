"""Iteration 51: Odoo sync mapping proof + since override + regression."""
import os
import sys
import time

import pytest
import requests

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/backend/migration")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://odoo-sync-ready.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PW = "HomeIVF@2026"


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=30)
    assert r.status_code == 200, r.text
    token = r.json().get("access_token")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _wait_running_done(client, timeout=90):
    """Wait for any running sync to complete."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"{BASE_URL}/api/admin/sync/runs", timeout=15)
        runs = r.json()
        if not runs or runs[0].get("status") != "running":
            return runs
        time.sleep(3)
    pytest.fail("Timed out waiting for prior sync run to finish")


# --- 1) Mapping proof against LIVE Odoo ---
class TestOdooMappingProof:
    def test_transform_lead_kamlesh(self):
        # Load env for odoo_migrate
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        import importlib
        odoo_migrate = importlib.import_module("odoo_migrate")
        fields, x_fields = odoo_migrate.get_lead_fields()
        recs = odoo_migrate.call(
            "crm.lead", "search_read",
            [["name", "ilike", "kamlesh yadav"], ["active", "in", [True, False]]],
            fields=fields, limit=1, order="write_date desc",
        )
        assert recs, "Expected at least one 'kamlesh yadav' lead in Odoo"
        doc = odoo_migrate.transform_lead(recs[0], x_fields)
        print("MAPPED:", {k: doc.get(k) for k in ["id", "name", "lead_stage", "tags", "follow_up_tag"]})
        assert doc["lead_stage"] == "Contact Attempt", f"lead_stage={doc.get('lead_stage')}"
        assert doc["tags"] == [26], f"tags={doc.get('tags')}"
        assert doc["follow_up_tag"] == "Follow UP 1", f"follow_up_tag={doc.get('follow_up_tag')}"


# --- 2) Since override on POST /api/admin/sync/start ---
class TestSinceOverride:
    def test_since_override_far_future(self, admin_client):
        _wait_running_done(admin_client)
        r = admin_client.post(f"{BASE_URL}/api/admin/sync/start", json={"since": "2099-01-01"}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["since"] == "2099-01-01 00:00:00", data
        assert data["mode"] == "delta", data
        rid = data["run_id"]

        # Wait for it to finish
        deadline = time.time() + 60
        final = None
        while time.time() < deadline:
            r2 = admin_client.get(f"{BASE_URL}/api/admin/sync/runs/{rid}", timeout=15)
            assert r2.status_code == 200
            final = r2.json()
            if final.get("status") != "running":
                break
            time.sleep(3)
        assert final and final.get("status") == "done", f"Run did not finish cleanly: {final}"
        prog = final.get("progress") or final.get("results") or {}
        leads = prog.get("leads") or {}
        assert leads.get("new", 0) == 0, f"expected 0 new, got {leads}"
        assert leads.get("updated", 0) == 0, f"expected 0 updated, got {leads}"

    def test_no_override_auto_since(self, admin_client):
        _wait_running_done(admin_client)
        r = admin_client.post(f"{BASE_URL}/api/admin/sync/start", json={}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "since" in data and data["since"], data
        assert data["mode"] in ("delta", "full")
        # Cancel-not-possible; but we can wait for it to end so it doesn't block next test class.
        # Instead we let it run in background — but subsequent test classes don't call sync.
        # We must still ensure we don't leave a stuck run: poll briefly, if it's a large full-sync it may take long.
        # For safety, wait up to 20s just to record status; don't fail if still running.
        rid = data["run_id"]
        for _ in range(7):
            r2 = admin_client.get(f"{BASE_URL}/api/admin/sync/runs/{rid}", timeout=15)
            if r2.json().get("status") != "running":
                break
            time.sleep(3)


# --- 3) Regression: leads perf endpoints ---
class TestLeadsRegression:
    def test_pipeline_bucket(self, admin_client):
        t0 = time.time()
        r = admin_client.get(f"{BASE_URL}/api/leads?bucket=pipeline&limit=50", timeout=20)
        dt = time.time() - t0
        assert r.status_code == 200, r.text
        assert dt < 8, f"took {dt:.1f}s"
        body = r.json()
        assert isinstance(body.get("items", body) if isinstance(body, dict) else body, list)

    def test_search_phone(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/leads?search=9998887766", timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        items = body.get("items") if isinstance(body, dict) else body
        assert isinstance(items, list) and len(items) == 1, f"got {len(items) if items else 0} results"
        assert items[0].get("name") == "Lead 650057", items[0].get("name")
