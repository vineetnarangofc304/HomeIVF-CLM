"""Regression test for Odoo Sync after XML-RPC timeout/retry fix in odoo_migrate.py."""
import os
import time
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "https://ivf-pipeline.preview.emergentagent.com"
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASS = "HomeIVF@2026"


def _login():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    token = r.json().get("access_token")
    assert token
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def test_sync_start_and_completes():
    s = _login()
    r = s.post(f"{BASE_URL}/api/admin/sync/start", json={}, timeout=30)
    assert r.status_code == 200, f"start failed: {r.status_code} {r.text}"
    body = r.json()
    run_id = body.get("run_id") or body.get("id")
    assert run_id, f"no run_id in {body}"

    deadline = time.time() + 120
    last = None
    while time.time() < deadline:
        rr = s.get(f"{BASE_URL}/api/admin/sync/runs/{run_id}", timeout=30)
        assert rr.status_code == 200, f"poll failed {rr.status_code} {rr.text}"
        last = rr.json()
        status = last.get("status")
        if status in ("done", "error", "failed"):
            break
        time.sleep(2)

    assert last is not None
    assert last.get("status") == "done", f"expected done, got: {last}"
    assert not last.get("error"), f"error in run: {last.get('error')}"
    # progress/results should contain per-entity buckets
    progress = last.get("progress") or last.get("results") or {}
    print("progress keys:", list(progress.keys()))
    for key in ("catalogs", "users", "templates", "leads"):
        assert key in progress, f"missing {key} in progress: {progress}"


def test_sync_status_after_run():
    s = _login()
    r = s.get(f"{BASE_URL}/api/admin/sync/status", timeout=30)
    assert r.status_code == 200, f"status failed {r.status_code} {r.text}"
    body = r.json()
    assert body.get("last_sync") or body.get("last_run") or body.get("last_record"), f"no last_sync in {body}"
