"""Tests for Admin → Migration sync (in-process background thread)."""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ivf-lead-ops.preview.emergentagent.com").rstrip("/")
ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
AGENT = {"email": "agent@homeivf.com", "password": "Agent@2026"}


def _login(creds):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text}"
    tok = r.json().get("access_token")
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def admin_client():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def agent_client():
    return _login(AGENT)


def _wait_for_no_running_sync(admin_client, timeout=180):
    """If a sync is running, wait until it's done before starting a new one."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = admin_client.post(f"{BASE_URL}/api/admin/sync/start", json={})
        if r.status_code == 200:
            return r.json()
        if r.status_code == 409:
            time.sleep(3)
            continue
        pytest.fail(f"sync/start unexpected {r.status_code}: {r.text}")
    pytest.fail("Timed out waiting for prior sync to finish")


def test_sync_start_admin_ok_and_completes(admin_client):
    started = _wait_for_no_running_sync(admin_client)
    assert "run_id" in started and started["run_id"]
    assert "since" in started
    assert "until" in started
    assert "mode" in started
    run_id = started["run_id"]

    expected_keys = {"catalogs", "users", "templates", "leads", "lead_messages",
                     "wa_channels", "wa_messages", "contacts", "open_activities"}

    status = None
    progress = {}
    deadline = time.time() + 180  # 3 min
    while time.time() < deadline:
        r = admin_client.get(f"{BASE_URL}/api/admin/sync/runs/{run_id}")
        assert r.status_code == 200, f"runs GET failed {r.status_code}: {r.text}"
        body = r.json()
        status = body.get("status")
        progress = body.get("progress") or {}
        if status in ("done", "error", "failed"):
            break
        time.sleep(3)

    assert status == "done", f"final status={status}, progress={progress}"
    missing = expected_keys - set(progress.keys())
    assert not missing, f"missing progress keys: {missing}; got {progress}"


def test_sync_status_reflects_last_run(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/sync/status")
    assert r.status_code == 200, r.text
    body = r.json()
    last = body.get("last_sync") or {}
    assert last.get("finished_at"), f"missing finished_at in {last}"
    assert last.get("run_id"), f"missing run_id in {last}"


def test_sync_start_forbidden_for_agent(agent_client):
    r = agent_client.post(f"{BASE_URL}/api/admin/sync/start", json={})
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


def test_migration_audit_returns_rows(admin_client):
    r = admin_client.post(f"{BASE_URL}/api/admin/migration/audit", json={}, timeout=180)
    assert r.status_code == 200, f"audit failed {r.status_code}: {r.text}"
    body = r.json()
    rows = body.get("rows") or body.get("entities") or body
    # If list-like
    if isinstance(rows, dict):
        # maybe {entity: {...}}
        assert len(rows) >= 5
        for name, row in rows.items():
            assert isinstance(row, dict)
    else:
        assert isinstance(rows, list) and len(rows) >= 5
