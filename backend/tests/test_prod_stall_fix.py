"""
Tests for production stall fix:
- Startup non-blocking (backend serves immediately)
- /api/reports/dashboard, /api/leads?limit=50, /api/ai/analytics return 200 quickly
- /api/ai/brain still works
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to frontend .env value baked in for local test runs
    BASE_URL = "https://ivf-lead-ops.preview.emergentagent.com"

ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASSWORD = "HomeIVF@2026"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(client):
    r = client.post(f"{BASE_URL}/api/auth/login",
                    json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                    timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def auth_client(client, admin_token):
    client.headers.update({"Authorization": f"Bearer {admin_token}"})
    return client


def test_health_fast(client):
    t0 = time.time()
    r = client.get(f"{BASE_URL}/api/health", timeout=10)
    dt = time.time() - t0
    assert r.status_code == 200
    assert dt < 3, f"health slow: {dt:.2f}s"


def test_reports_dashboard(auth_client):
    t0 = time.time()
    r = auth_client.get(f"{BASE_URL}/api/reports/dashboard", timeout=20)
    dt = time.time() - t0
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    data = r.json()
    assert isinstance(data, dict)
    assert dt < 10, f"reports/dashboard slow: {dt:.2f}s"


def test_leads_list_paginated(auth_client):
    t0 = time.time()
    r = auth_client.get(f"{BASE_URL}/api/leads?limit=50", timeout=20)
    dt = time.time() - t0
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    data = r.json()
    # Accept both list or paginated dict
    if isinstance(data, dict):
        items = data.get("items") or data.get("results") or data.get("data") or []
    else:
        items = data
    assert isinstance(items, list)
    assert len(items) <= 50
    assert len(items) > 0, "expected some leads in production data"
    assert dt < 10, f"leads slow: {dt:.2f}s"


def test_ai_analytics_fast(auth_client):
    t0 = time.time()
    r = auth_client.get(f"{BASE_URL}/api/ai/analytics", timeout=25)
    dt = time.time() - t0
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    data = r.json()
    assert isinstance(data, dict)
    # Should have some analytics keys
    assert len(data.keys()) >= 3
    assert dt < 15, f"ai/analytics slow: {dt:.2f}s (should be <15s w/ concurrent gather)"


def test_ai_brain_top_callers(auth_client):
    t0 = time.time()
    r = auth_client.post(f"{BASE_URL}/api/ai/brain",
                         json={"question": "Top callers by conversion rate"},
                         timeout=45)
    dt = time.time() - t0
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    data = r.json()
    assert "answer" in data or "text" in data or "result" in data or "chart" in data
    print(f"brain answered in {dt:.2f}s")
