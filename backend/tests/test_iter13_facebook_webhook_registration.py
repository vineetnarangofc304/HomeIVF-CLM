"""Iteration 13 — Facebook Lead Ads: webhook registration + LIVE diagnose flow.

Preview settings DB contains REAL Meta credentials for HomeIVF (App ID
736963545504625, live Page Access Token pointing to Page 273380505860843).
These tests hit the LIVE Meta Graph API v25.0. Do NOT wipe/overwrite the
facebook settings — snapshot & restore instead.

Covers the 6 items in the review request:
  1) GET  /api/admin/facebook/diagnose            → configured=true, 3 checks ok
  2) POST /api/admin/facebook/register-webhook    → registers webhook w/ Meta
  3) POST /api/admin/facebook/register-webhook    → 400 on non-https URL
  4) POST /api/admin/facebook/test                → creates a CRM lead
  5) Auth/role: unauth → 401/403 for both admin endpoints
  6) GET  /api/webhooks/facebook (verify handshake)  → challenge / 403
"""
import os
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://homeivf-crm.preview.emergentagent.com",
).rstrip("/")
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASS = "HomeIVF@2026"
CALLBACK_URL = f"{BASE_URL}/api/webhooks/facebook"
EXPECTED_VERIFY_TOKEN = "homeivf_fb_verify_2026"
EXPECTED_PAGE_ID = "273380505860843"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


# =========================================================
# 1. Live diagnose — expect all 3 checks ok=true
# =========================================================
def test_diagnose_live_all_checks_ok(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/facebook/diagnose", timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    print("DIAGNOSE:", data)
    assert data.get("configured") is True, f"configured must be True, got {data}"
    assert data.get("verify_token_set") is True
    assert data.get("page_id_set") is True
    checks = data.get("checks") or []
    names = [c.get("name") for c in checks]
    # Must contain three named checks
    assert "Access Token" in names, f"Missing 'Access Token' check; got {names}"
    assert "Page subscribed to leadgen" in names, f"Missing subscribed-to-leadgen check; got {names}"
    assert "App leadgen webhook" in names, f"Missing App leadgen webhook check; got {names}"

    by_name = {c["name"]: c for c in checks}
    assert by_name["Access Token"]["ok"] is True, by_name["Access Token"]
    # Token should point to the HomeIVF Page ID
    detail_tok = str(by_name["Access Token"].get("detail", ""))
    assert EXPECTED_PAGE_ID in detail_tok, f"Access-Token detail missing page id: {detail_tok}"

    assert by_name["Page subscribed to leadgen"]["ok"] is True, by_name["Page subscribed to leadgen"]
    assert by_name["App leadgen webhook"]["ok"] is True, by_name["App leadgen webhook"]
    # Callback URL should be the preview URL
    detail_wh = str(by_name["App leadgen webhook"].get("detail", ""))
    assert "https://" in detail_wh, f"webhook detail missing url: {detail_wh}"

    next_step = data.get("next_step") or ""
    assert "Connection looks good" in next_step, f"unexpected next_step: {next_step}"


# =========================================================
# 2. Register webhook (LIVE call to Meta) — valid https URL
# =========================================================
def test_register_webhook_success(admin_client):
    r = admin_client.post(
        f"{BASE_URL}/api/admin/facebook/register-webhook",
        json={"callback_url": CALLBACK_URL},
        timeout=60,
    )
    assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
    data = r.json()
    print("REGISTER_WEBHOOK:", data)
    assert data.get("ok") is True
    assert data.get("callback_url") == CALLBACK_URL
    resp = data.get("response") or {}
    assert resp.get("success") is True, f"Meta didn't return success:true → {resp}"


# =========================================================
# 3. Register webhook — non-https callback_url → 400
# =========================================================
def test_register_webhook_rejects_non_https(admin_client):
    r = admin_client.post(
        f"{BASE_URL}/api/admin/facebook/register-webhook",
        json={"callback_url": "http://foo"},
        timeout=30,
    )
    assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text}"
    # Response should mention https requirement
    body = r.text.lower()
    assert "https" in body, f"400 detail should mention https, got {r.text}"


# =========================================================
# 4. Admin test — create CRM lead via field_data
# =========================================================
def test_admin_facebook_test_creates_lead(admin_client):
    payload = {
        "field_data": [
            {"name": "full_name", "values": ["QA Test Lead"]},
            {"name": "phone_number", "values": ["9876500099"]},
            {"name": "email", "values": ["qa@example.com"]},
        ],
        "leadgen_id": "QA_TEST",
    }
    r = admin_client.post(f"{BASE_URL}/api/admin/facebook/test", json=payload, timeout=45)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True
    lead_id = data.get("lead_id") or (data.get("lead") or {}).get("id")
    assert lead_id, f"lead_id missing in response: {data}"
    lead = data.get("lead") or {}

    # Field mapping assertions — full_name may be mapped to `name` (per current
    # saved settings field_mapping) or `contact_name` (DEFAULT_MAP). Accept either.
    display_name = lead.get("contact_name") or lead.get("name")
    assert display_name == "QA Test Lead", f"name/contact_name mismatch: {lead}"
    assert lead.get("phone") == "9876500099", lead
    assert lead.get("email_from") == "qa@example.com", lead
    assert lead.get("source_lead") == "Meta Lead Ads", lead
    assert lead.get("facebook_lead") is True

    # GET verification — data persisted
    r2 = admin_client.get(f"{BASE_URL}/api/leads/{lead_id}", timeout=30)
    assert r2.status_code == 200, r2.text
    fetched = r2.json()
    assert fetched.get("phone") == "9876500099"
    assert fetched.get("facebook_lead") is True

    # Cleanup — soft-delete via /lost
    admin_client.post(f"{BASE_URL}/api/leads/{lead_id}/lost",
                      json={"note": "iter13 fb qa cleanup"}, timeout=30)


# =========================================================
# 5. Role enforcement — unauthenticated
# =========================================================
def test_diagnose_requires_auth():
    r = requests.get(f"{BASE_URL}/api/admin/facebook/diagnose", timeout=30)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code} {r.text}"


def test_register_webhook_requires_auth():
    r = requests.post(
        f"{BASE_URL}/api/admin/facebook/register-webhook",
        json={"callback_url": CALLBACK_URL},
        timeout=30,
    )
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code} {r.text}"


def test_register_webhook_forbidden_for_caller():
    """Caller role should be rejected (register-webhook is admin-only)."""
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "caller1@homeivf.com", "password": "HomeIVF@123"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"caller login unavailable: {r.status_code}")
    tok = r.json().get("access_token")
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    r2 = s.post(f"{BASE_URL}/api/admin/facebook/register-webhook",
                json={"callback_url": CALLBACK_URL}, timeout=30)
    assert r2.status_code in (401, 403), f"caller must be blocked, got {r2.status_code}: {r2.text}"


# =========================================================
# 6. Webhook verify handshake
# =========================================================
def test_webhook_verify_success():
    r = requests.get(
        f"{BASE_URL}/api/webhooks/facebook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": EXPECTED_VERIFY_TOKEN,
            "hub.challenge": "12345",
        },
        timeout=30,
    )
    assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
    assert r.text == "12345", f"expected plain challenge '12345', got {r.text!r}"


def test_webhook_verify_wrong_token():
    r = requests.get(
        f"{BASE_URL}/api/webhooks/facebook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token_xyz",
            "hub.challenge": "12345",
        },
        timeout=30,
    )
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"
