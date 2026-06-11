"""Sync feature regression tests (delta sync endpoints)."""
import os

import requests

BASE = None
TOKEN = None


def setup_module():
    global BASE, TOKEN
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE = line.strip().split("=", 1)[1].strip('"')
    r = requests.post(f"{BASE}/api/auth/login", json={"email": "admin@homeivf.com", "password": "HomeIVF@2026"}, timeout=30)
    TOKEN = r.json()["access_token"]


def hdr():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_sync_status_shape():
    r = requests.get(f"{BASE}/api/admin/sync/status", headers=hdr(), timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert "last_record" in d and "counts" in d and "next_since" in d and "mode" in d
    assert d["counts"]["leads"] > 0
    assert d["mode"] in ("delta", "full")
    assert d["last_record"]["leads_write_date"]


def test_sync_runs_list():
    r = requests.get(f"{BASE}/api/admin/sync/runs", headers=hdr(), timeout=30)
    assert r.status_code == 200
    runs = r.json()
    assert isinstance(runs, list)
    if runs:
        assert {"run_id", "status", "since", "until"} <= set(runs[0].keys())


def test_sync_run_detail_404():
    r = requests.get(f"{BASE}/api/admin/sync/runs/999999", headers=hdr(), timeout=30)
    assert r.status_code == 404


def test_sync_start_forbidden_for_caller():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": "caller1@homeivf.com", "password": "HomeIVF@123"}, timeout=30)
    caller_token = r.json()["access_token"]
    r = requests.post(f"{BASE}/api/admin/sync/start", headers={"Authorization": f"Bearer {caller_token}"}, timeout=30)
    assert r.status_code == 403
