"""Iteration 23: verify 'contains name' last-resort fallback + exclusion list
in /app/backend/routes/facebook.py _map_and_create_lead().

New behavior:
- Any field whose normalized key CONTAINS 'name' becomes the lead name
  (e.g. 'what is your name?' → 'Sunita Devi').
- Excluded keys containing company/form/page/user/product/brand/clinic/business
  do NOT populate the name (e.g. company_name='ACME Clinic' → falls back to phone).
"""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASSWORD = "HomeIVF@2026"


@pytest.fixture(scope="module")
def headers():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _fb_test(headers, field_data, phone="9222200000"):
    has_phone = any(str(f.get("name", "")).lower() in ("phone_number", "phone") for f in field_data)
    if not has_phone:
        field_data = field_data + [{"name": "phone_number", "values": [phone]}]
    body = {
        "field_data": field_data,
        "leadgen_id": f"TEST_ITER23_{phone}",
        "form_id": "FORM_ITER23",
        "form_name": "Iter23 Test Form",
        "campaign_name": "Iter23 Camp",
    }
    r = requests.post(f"{BASE_URL}/api/admin/facebook/test",
                      headers=headers, json=body, timeout=20)
    assert r.status_code == 200, f"fb/test failed: {r.status_code} {r.text}"
    return r.json()["lead"]


# ---- Case 1: 'what is your name?' → Sunita Devi (new last-resort fallback) ----
def test_what_is_your_name(headers):
    lead = _fb_test(headers, [
        {"name": "what is your name?", "values": ["Sunita Devi"]},
        {"name": "email", "values": ["sunita@example.com"]},
    ], phone="9222200001")
    assert lead["name"] == "Sunita Devi", f"expected 'Sunita Devi', got {lead.get('name')!r}"
    assert lead.get("contact_name") == "Sunita Devi"


# ---- Case 2: company_name only + phone → NOT ACME Clinic; falls back to phone ----
def test_company_name_excluded(headers):
    lead = _fb_test(headers, [
        {"name": "company_name", "values": ["ACME Clinic"]},
    ], phone="9222200002")
    assert lead["name"] != "ACME Clinic", f"company_name leaked into name: {lead.get('name')!r}"
    assert lead["name"] == "9222200002", f"expected phone fallback, got {lead.get('name')!r}"
    assert not lead.get("contact_name"), f"contact_name should be empty, got {lead.get('contact_name')!r}"


# ---- Case 3: clinic_name / business_name / brand_name also excluded ----
@pytest.mark.parametrize("bad_key,bad_val,phone", [
    ("clinic_name", "HomeIVF Clinic", "9222200003"),
    ("business_name", "Acme Biz", "9222200004"),
    ("brand_name", "SuperBrand", "9222200005"),
    ("form_name", "My Form", "9222200006"),
    ("page_name", "FB Page", "9222200007"),
])
def test_excluded_name_keys(headers, bad_key, bad_val, phone):
    lead = _fb_test(headers, [
        {"name": bad_key, "values": [bad_val]},
    ], phone=phone)
    assert lead["name"] != bad_val, f"{bad_key}={bad_val} leaked into name"
    assert lead["name"] == phone, f"expected phone fallback for {bad_key}, got {lead.get('name')!r}"


# ---- Case 4: first_name + last_name still combined (regression) ----
def test_first_last_regression(headers):
    lead = _fb_test(headers, [
        {"name": "first_name", "values": ["First"]},
        {"name": "last_name", "values": ["Last"]},
    ], phone="9222200008")
    assert lead["name"] == "First Last"
    assert lead.get("contact_name") == "First Last"


# ---- Case 5: standard full_name still mapped (regression) ----
def test_standard_full_name_regression(headers):
    lead = _fb_test(headers, [
        {"name": "full_name", "values": ["Priya Nair"]},
    ], phone="9222200009")
    assert lead["name"] == "Priya Nair"


# ---- Case 6: only phone/email → name = phone (regression) ----
def test_only_phone_email(headers):
    lead = _fb_test(headers, [
        {"name": "email", "values": ["only@example.com"]},
    ], phone="9222200010")
    assert lead["name"] == "9222200010"
    assert not lead.get("contact_name")


# ---- Case 7: created lead metadata: source, dates, round-robin, custom Q&A ----
def test_created_lead_metadata(headers):
    lead = _fb_test(headers, [
        {"name": "what is your name?", "values": ["Ramesh Patel"]},
        {"name": "want to consult an ivf expert at home", "values": ["yes"]},
    ], phone="9222200011")
    assert lead.get("source_lead") == "Meta Lead Ads"
    assert lead.get("create_date")
    assert lead.get("user_id"), "round-robin caller assignment missing"
    assert lead.get("facebook_lead") is True
    assert lead["name"] == "Ramesh Patel"
    custom = lead.get("custom") or {}
    # Real Q&A preserved
    assert any("consult" in k for k in custom), f"consult Q&A missing: {list(custom.keys())}"
    # Name-part / name-containing fields NOT in custom
    assert not any("name" in k.lower() for k in custom), f"name field leaked into custom: {list(custom.keys())}"


# ---- Case 8: /recent-leads and /diagnose return 200 (regression) ----
def test_recent_leads_endpoint(headers):
    r = requests.get(f"{BASE_URL}/api/admin/facebook/recent-leads", headers=headers, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "total" in data and isinstance(data["leads"], list)


def test_diagnose_endpoint(headers):
    r = requests.get(f"{BASE_URL}/api/admin/facebook/diagnose", headers=headers, timeout=15)
    assert r.status_code == 200
    assert "checks" in r.json()


# ---- Case 9: invalid-signature webhook → 401 (or 503 if not configured) ----
def test_invalid_signature_webhook():
    r = requests.post(f"{BASE_URL}/api/webhooks/facebook",
                      headers={"X-Hub-Signature-256": "sha256=deadbeef",
                              "Content-Type": "application/json"},
                      data=b'{"entry":[]}', timeout=15)
    assert r.status_code in (401, 503), f"got {r.status_code} {r.text}"


def test_backend_healthy():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200
