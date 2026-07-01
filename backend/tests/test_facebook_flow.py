"""Facebook Lead Ads integration tests — iteration 11.

Covers:
- Admin diagnose endpoint (no live creds expected)
- Webhook GET verification (valid + wrong verify_token)
- Webhook POST signature enforcement (invalid + valid HMAC)
- Admin test-lead simulation + cleanup
- Restores facebook settings to a clean state at teardown.
"""
import os
import hmac
import hashlib
import json
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASSWORD = "HomeIVF@2026"

FB_KEY_URL = f"{BASE_URL}/api/admin/settings"


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def saved_original_fb(admin_client):
    """Snapshot current facebook settings; restore at teardown."""
    r = admin_client.get(f"{BASE_URL}/api/admin/settings")
    original = None
    if r.status_code == 200:
        try:
            original = (r.json() or {}).get("facebook")
        except Exception:
            original = None
    yield original
    # Restore — drop mongo fields and re-post as a clean value dict
    restore_val = {
        "graph_api_version": "v25.0",
        "source_default": "Meta Lead Ads",
        "field_mapping": {"full_name": "name", "phone_number": "phone"},
    }
    if isinstance(original, dict):
        clean = {k: v for k, v in original.items() if k not in ("_id", "key")}
        if clean:
            restore_val = clean
    admin_client.patch(FB_KEY_URL, json={"key": "facebook", "value": restore_val})


def _set_fb_settings(admin_client, value: dict):
    r = admin_client.patch(FB_KEY_URL, json={"key": "facebook", "value": value})
    assert r.status_code in (200, 201, 204), f"PATCH settings failed: {r.status_code} {r.text}"


# ---------- 1. Diagnose ----------
def test_diagnose_returns_structured_response(admin_client, saved_original_fb):
    # Explicitly blank the token fields so 'configured' becomes False
    _set_fb_settings(admin_client, {
        "graph_api_version": "v25.0",
        "source_default": "Meta Lead Ads",
        "field_mapping": {},
        "app_secret": "",
        "page_access_token": "",
        "verify_token": "",
        "page_id": "",
    })
    r = admin_client.get(f"{BASE_URL}/api/admin/facebook/diagnose")
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ["configured", "verify_token_set", "page_id_set", "leads_captured", "checks", "next_step"]:
        assert k in data, f"missing key {k} in diagnose response"
    assert data["configured"] is False, f"unexpected configured=True; response={data}"
    assert isinstance(data["checks"], list) and len(data["checks"]) >= 1
    first = data["checks"][0]
    assert first["name"] == "Page Access Token"
    assert first["ok"] is False
    assert data["next_step"], "next_step should be populated when token missing"


# ---------- 2. Webhook GET verification ----------
def test_webhook_get_verification_success(admin_client):
    _set_fb_settings(admin_client, {
        "verify_token": "HIVF_TEST_123",
        "app_secret": "testsecret",
        "page_access_token": "testtoken",
        "page_id": "123",
        "graph_api_version": "v25.0",
    })
    r = requests.get(
        f"{BASE_URL}/api/webhooks/facebook",
        params={"hub.mode": "subscribe", "hub.verify_token": "HIVF_TEST_123", "hub.challenge": "CHALLENGE99"},
    )
    assert r.status_code == 200, r.text
    assert r.text == "CHALLENGE99", f"unexpected body: {r.text!r}"


def test_webhook_get_verification_wrong_token(admin_client):
    r = requests.get(
        f"{BASE_URL}/api/webhooks/facebook",
        params={"hub.mode": "subscribe", "hub.verify_token": "WRONG", "hub.challenge": "X"},
    )
    assert r.status_code == 403


# ---------- 3. Webhook POST signature enforcement ----------
def _sample_leadgen_payload():
    return {
        "object": "page",
        "entry": [{
            "id": "123",
            "changes": [{
                "field": "leadgen",
                "value": {"leadgen_id": "9999999", "form_id": "FORM1", "page_id": "123"},
            }],
        }],
    }


def test_webhook_post_rejects_invalid_signature(admin_client):
    body = json.dumps(_sample_leadgen_payload()).encode()
    r = requests.post(
        f"{BASE_URL}/api/webhooks/facebook",
        data=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert r.status_code == 401, f"expected 401 got {r.status_code} {r.text}"


def test_webhook_post_missing_signature(admin_client):
    body = json.dumps(_sample_leadgen_payload()).encode()
    r = requests.post(
        f"{BASE_URL}/api/webhooks/facebook",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_webhook_post_valid_signature_graceful(admin_client):
    body = json.dumps(_sample_leadgen_payload()).encode()
    sig = "sha256=" + hmac.new(b"testsecret", body, hashlib.sha256).hexdigest()
    r = requests.post(
        f"{BASE_URL}/api/webhooks/facebook",
        data=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert r.status_code == 200, f"expected 200 got {r.status_code} {r.text}"
    j = r.json()
    assert j.get("status") == "ok"
    assert "created" in j
    # Fake token → Graph fetch fails silently → created == 0
    assert j["created"] == 0


# ---------- 4. Admin test-lead creation ----------
def test_admin_facebook_test_creates_lead(admin_client):
    payload = {"field_data": [
        {"name": "full_name", "values": ["TEST_FB Lead"]},
        {"name": "phone_number", "values": ["9876500011"]},
        {"name": "email", "values": ["fbtest@example.com"]},
    ]}
    r = admin_client.post(f"{BASE_URL}/api/admin/facebook/test", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True
    lead = data.get("lead") or {}
    lead_id = lead.get("id") or data.get("lead_id")
    assert lead_id, "no lead_id returned"

    # Field mapping assertions
    assert lead.get("facebook_lead") is True
    assert lead.get("contact_name") == "TEST_FB Lead"
    assert lead.get("phone") == "9876500011"
    assert lead.get("email_from") == "fbtest@example.com"

    # GET verification
    r2 = admin_client.get(f"{BASE_URL}/api/leads/{lead_id}")
    assert r2.status_code == 200, r2.text
    fetched = r2.json()
    assert fetched.get("facebook_lead") is True
    assert fetched.get("phone") == "9876500011"

    # Cleanup — mark lost (soft delete). No hard delete endpoint exists.
    d = admin_client.post(f"{BASE_URL}/api/leads/{lead_id}/lost", json={"note": "cleanup by iter11 fb test"})
    assert d.status_code in (200, 204), f"lost failed: {d.status_code} {d.text}"
