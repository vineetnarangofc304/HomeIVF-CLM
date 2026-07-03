"""Iteration 18: verify /api/admin/facebook/diagnose now includes
'Token ↔ App match' and 'leads_retrieval permission' checks (debug_token integration).
Also regressions: webhook signature 401, webhook-log endpoint, recent_webhook_deliveries."""
import os
import requests

def _load_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _load_url()
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PWD = "HomeIVF@2026"


def _admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


def test_backend_health():
    r = requests.get(f"{BASE_URL}/api/health", timeout=10)
    # Some apps use /api/ping etc. — try both
    if r.status_code == 404:
        r = requests.get(f"{BASE_URL}/api/", timeout=10)
    assert r.status_code < 500


def test_diagnose_includes_new_checks():
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/admin/facebook/diagnose", timeout=30)
    assert r.status_code == 200, f"diagnose returned {r.status_code}: {r.text[:400]}"
    data = r.json()
    assert "checks" in data and isinstance(data["checks"], list), "checks array missing"
    assert "recent_webhook_deliveries" in data and isinstance(data["recent_webhook_deliveries"], list)

    names = [c.get("name") for c in data["checks"]]
    print("Diagnose checks present:", names)
    assert "Access Token" in names, f"missing 'Access Token' check; got {names}"
    assert "Token ↔ App match" in names, f"missing 'Token ↔ App match' check; got {names}"
    assert "leads_retrieval permission" in names, f"missing 'leads_retrieval permission' check; got {names}"

    # Ensure each check has ok + detail
    for c in data["checks"]:
        assert "ok" in c and "detail" in c, f"malformed check: {c}"


def test_webhook_log_admin():
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/admin/facebook/webhook-log", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "count" in data and "logs" in data
    assert isinstance(data["logs"], list)


def test_webhook_invalid_signature_returns_401_and_logs():
    # Get baseline count
    s = _admin_session()
    r0 = s.get(f"{BASE_URL}/api/admin/facebook/webhook-log", timeout=15)
    before = r0.json().get("count", 0)

    body = b'{"entry":[{"changes":[{"field":"leadgen","value":{"leadgen_id":"TEST_ITER18_BADSIG"}}]}]}'
    r = requests.post(
        f"{BASE_URL}/api/webhooks/facebook",
        data=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + "0" * 64},
        timeout=15,
    )
    # If FB is not configured we would get 503; test_credentials says configured
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:200]}"

    r1 = s.get(f"{BASE_URL}/api/admin/facebook/webhook-log", timeout=15)
    after = r1.json().get("count", 0)
    assert after >= before, "webhook log count should not decrease"
    # confirm a recent 'rejected' entry exists
    logs = r1.json().get("logs", [])
    assert any(l.get("status") == "rejected" for l in logs[:10]), "no recent 'rejected' entry found"


def test_webhook_log_requires_auth():
    r = requests.get(f"{BASE_URL}/api/admin/facebook/webhook-log", timeout=10)
    assert r.status_code in (401, 403)
