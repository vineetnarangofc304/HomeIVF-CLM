"""AI Insights (Phase 2) backend tests — /api/ai/analytics + /api/ai/brain."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback: read frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    token = r.json().get("access_token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def test_analytics_ok(client):
    t0 = time.time()
    r = client.get(f"{BASE_URL}/api/ai/analytics", timeout=30)
    dt = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    assert "kpis" in j and "funnel" in j and "source" in j and "caller" in j
    assert "platform" in j and "geo" in j and "trend" in j
    k = j["kpis"]
    assert isinstance(k["total"], int) and k["total"] > 0
    assert isinstance(k["converted"], int)
    assert isinstance(k["conversion_rate"], (int, float))
    # each chart should have some data
    assert len(j["funnel"]) > 0
    assert len(j["source"]) > 0
    assert len(j["caller"]) > 0
    assert len(j["trend"]) > 0
    print(f"analytics latency: {dt:.2f}s  kpis={k}")


def test_brain_number_question(client):
    body = {"question": "How many total leads do we have?", "session_id": "test-num"}
    r = client.post(f"{BASE_URL}/api/ai/brain", json=body, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "answer" in j and "chart" in j
    assert j["chart"]["type"] == "number"
    assert j["chart"]["data"] and isinstance(j["chart"]["data"][0]["value"], int)


def test_brain_top_callers(client):
    body = {"question": "Top callers by conversion rate", "session_id": "test-callers"}
    r = client.post(f"{BASE_URL}/api/ai/brain", json=body, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["chart"]["type"] in ("bar", "line", "pie")
    assert len(j["chart"]["data"]) > 0
    assert j["spec"].get("dimension") == "user_id"


def test_brain_history(client):
    r = client.get(f"{BASE_URL}/api/ai/brain/history?session_id=test-num", timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list) and len(rows) >= 1
    assert "question" in rows[0]


def test_brain_requires_reports_perm(client):
    # Login as caller (should be denied reports permission)
    s2 = requests.Session()
    r = s2.post(f"{BASE_URL}/api/auth/login",
                json={"email": "agent@homeivf.com", "password": "Agent@2026"}, timeout=15)
    if r.status_code != 200:
        pytest.skip("caller login not available")
    token = r.json().get("access_token")
    if token:
        s2.headers.update({"Authorization": f"Bearer {token}"})
    r2 = s2.get(f"{BASE_URL}/api/ai/analytics", timeout=15)
    assert r2.status_code in (401, 403), f"expected forbidden, got {r2.status_code}"
