"""Iter30: WhatsApp diagnose endpoint + light regression."""
import os
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASS = "HomeIVF@2026"


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


# ---- DIAGNOSE ENDPOINT ----
class TestDiagnose:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/whatsapp/diagnose", timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_diagnose_200_shape(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/whatsapp/diagnose", timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("verdict", "next_step", "checks", "callback_url", "waba_id"):
            assert k in data, f"missing key: {k}"
        assert isinstance(data["checks"], list) and len(data["checks"]) >= 1
        for c in data["checks"]:
            assert set(["key", "ok", "label", "detail"]).issubset(c.keys())
            assert isinstance(c["ok"], bool)

    def test_diagnose_healthy_on_preview(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/whatsapp/diagnose", timeout=60)
        data = r.json()
        # matched_hits>0 from iter29 tests → verdict should be 'healthy'
        assert data["verdict"] == "healthy", f"expected healthy, got {data['verdict']} - {data['next_step']}"


# ---- REGRESSION ----
class TestRegression:
    def test_status(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/whatsapp/status", timeout=30)
        assert r.status_code == 200, r.text

    def test_webhook_log(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/whatsapp/webhook-log", timeout=30)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_subscribe_no_500(self, admin_client):
        r = admin_client.post(f"{BASE_URL}/api/admin/whatsapp/subscribe", timeout=30)
        assert r.status_code != 500, r.text
        assert r.status_code in (200, 400)

    def test_subscribed_apps_no_500(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/whatsapp/subscribed-apps", timeout=30)
        assert r.status_code != 500, r.text
        assert r.status_code in (200, 400)
