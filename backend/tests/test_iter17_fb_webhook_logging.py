"""Iteration 17 — Meta webhook delivery logging.

Covers:
  1. POST /api/webhooks/facebook with INVALID sig → 401 + 'rejected' log entry
  2. POST /api/webhooks/facebook with VALID sig, unknown leadgen_id → 200 + 'error' log entry
  3. GET /api/admin/facebook/webhook-log requires admin/manager + returns {count, logs}
  4. GET /api/admin/facebook/diagnose includes recent_webhook_deliveries
  5. Regression: 'Meta Lead Ads' still in source_lead catalog
"""
import os
import json
import hmac
import hashlib
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    token = r.json().get("access_token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def app_secret():
    async def _get():
        c = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = c[os.environ.get("DB_NAME", "test_database")]
        s = await db.settings.find_one({"key": "facebook"})
        return s.get("app_secret") if s else None
    secret = asyncio.get_event_loop().run_until_complete(_get())
    assert secret and len(secret) >= 16, "facebook.app_secret not set in DB"
    return secret


def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---- 1. Invalid signature → 401 + rejected log ----
def test_invalid_signature_returns_401_and_logs_rejected(admin_session):
    body = json.dumps({"entry": [{"changes": [{"field": "leadgen", "value": {"leadgen_id": "999"}}]}]}).encode()
    r = requests.post(
        f"{API}/webhooks/facebook",
        data=body,
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64, "Content-Type": "application/json"},
        timeout=15,
    )
    assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text}"

    lr = admin_session.get(f"{API}/admin/facebook/webhook-log", timeout=15)
    assert lr.status_code == 200, lr.text
    data = lr.json()
    assert "count" in data and "logs" in data
    assert isinstance(data["logs"], list) and len(data["logs"]) > 0
    top = data["logs"][0]
    assert top["status"] == "rejected", f"expected top log rejected, got {top}"
    assert "signature" in top["detail"].lower() or "app secret" in top["detail"].lower()
    # sorted most-recent-first: at descending
    ats = [l["at"] for l in data["logs"]]
    assert ats == sorted(ats, reverse=True)


# ---- 2. Valid signature + bad leadgen_id → 200 + error log ----
def test_valid_signature_bad_leadgen_returns_200_and_logs_error(admin_session, app_secret):
    body = json.dumps({
        "entry": [{"changes": [{"field": "leadgen",
                                 "value": {"leadgen_id": "000000000000000_TEST_ITER17"}}]}]
    }).encode()
    sig = _sig(app_secret, body)
    r = requests.post(
        f"{API}/webhooks/facebook",
        data=body,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
        timeout=30,
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
    assert r.json().get("status") == "ok"

    lr = admin_session.get(f"{API}/admin/facebook/webhook-log", timeout=15)
    logs = lr.json()["logs"]
    # find an entry for our leadgen_id
    matching = [l for l in logs if l.get("leadgen_id") == "000000000000000_TEST_ITER17"]
    assert matching, f"no log entry for our leadgen_id — top logs: {logs[:3]}"
    top = matching[0]
    assert top["status"] == "error", f"expected error, got {top}"
    assert "graph" in top["detail"].lower() or "token" in top["detail"].lower() or "invalid" in top["detail"].lower()


# ---- 3. Auth required on webhook-log ----
def test_webhook_log_requires_auth():
    r = requests.get(f"{API}/admin/facebook/webhook-log", timeout=15)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


def test_webhook_log_response_shape(admin_session):
    r = admin_session.get(f"{API}/admin/facebook/webhook-log", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert set(["count", "logs"]).issubset(data.keys())
    assert isinstance(data["count"], int)
    for l in data["logs"][:5]:
        assert "at" in l and "status" in l and "detail" in l


# ---- 4. Diagnose includes recent_webhook_deliveries ----
def test_diagnose_includes_recent_webhook_deliveries(admin_session):
    r = admin_session.get(f"{API}/admin/facebook/diagnose", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "recent_webhook_deliveries" in data
    assert isinstance(data["recent_webhook_deliveries"], list)
    assert len(data["recent_webhook_deliveries"]) <= 10
    # After the two POSTs above there should be some deliveries
    assert len(data["recent_webhook_deliveries"]) >= 1


# ---- 5. Regression: Meta Lead Ads still in source_lead catalog ----
def test_meta_lead_ads_in_source_catalog(admin_session):
    # Common endpoints for catalog lookup
    r = admin_session.get(f"{API}/catalogs", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    sources = data.get("source_lead") or []
    names = [(s.get("name") if isinstance(s, dict) else s) for s in sources]
    assert "Meta Lead Ads" in names, f"Meta Lead Ads missing in source_lead: {names}"
