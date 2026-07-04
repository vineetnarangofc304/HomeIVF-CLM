"""Iteration 22: verify Facebook lead NAME derivation fix.

Fix under test in /app/backend/routes/facebook.py:
- DEFAULT_MAP no longer maps 'first_name' → contact_name
- _map_and_create_lead now derives name from name-like keys (full_name, name, your_name,
  spaced/capitalized variants) or first+last, and does NOT store name-part fields as
  x_custom_* Q&A extras.
"""
import os
import re
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASSWORD = "HomeIVF@2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _fb_test(headers, field_data, phone="9999900000"):
    # ensure a phone is present for lead validity, but only when caller didn't pass one
    has_phone = any(str(f.get("name", "")).lower() in ("phone_number", "phone") for f in field_data)
    if not has_phone:
        field_data = field_data + [{"name": "phone_number", "values": [phone]}]
    body = {
        "field_data": field_data,
        "leadgen_id": f"TEST_ITER22_{phone}",
        "form_id": "FORM_ITER22",
        "form_name": "Iter22 Test Form",
        "campaign_name": "Iter22 Camp",
    }
    r = requests.post(f"{BASE_URL}/api/admin/facebook/test",
                      headers=headers, json=body, timeout=20)
    assert r.status_code == 200, f"fb/test failed: {r.status_code} {r.text}"
    return r.json()["lead"]


# ---- Case 1: first_name + last_name → combined ----
def test_first_plus_last_name(headers):
    lead = _fb_test(headers, [
        {"name": "first_name", "values": ["Akhil"]},
        {"name": "last_name", "values": ["Sharma"]},
        {"name": "email", "values": ["akhil@example.com"]},
    ], phone="9111100001")
    assert lead["name"] == "Akhil Sharma", f"name={lead.get('name')}"
    assert lead.get("contact_name") == "Akhil Sharma"
    custom = lead.get("custom") or {}
    # name-part fields must not be in Q&A extras
    assert not any(k.startswith("x_custom_first") or k.startswith("x_custom_last") for k in custom), custom


# ---- Case 2: spaced/capitalized 'Full Name' → mapped, not in custom ----
def test_spaced_full_name_key(headers):
    lead = _fb_test(headers, [
        {"name": "Full Name", "values": ["Ravi Kumar"]},
        {"name": "email", "values": ["ravi@example.com"]},
    ], phone="9111100002")
    assert lead["name"] == "Ravi Kumar"
    assert lead.get("contact_name") == "Ravi Kumar"
    custom = lead.get("custom") or {}
    # must not be stored as x_custom_full_name
    assert "x_custom_full_name" not in custom, custom
    assert not any("full" in k and "name" in k for k in custom), custom


# ---- Case 3: only first_name ----
def test_only_first_name(headers):
    lead = _fb_test(headers, [
        {"name": "first_name", "values": ["Meena"]},
    ], phone="9111100003")
    assert lead["name"] == "Meena"
    assert lead.get("contact_name") == "Meena"
    custom = lead.get("custom") or {}
    assert "x_custom_first_name" not in custom


# ---- Case 4: standard full_name (regression) ----
def test_standard_full_name(headers):
    lead = _fb_test(headers, [
        {"name": "full_name", "values": ["Priya Nair"]},
        {"name": "email", "values": ["priya@example.com"]},
        {"name": "city", "values": ["Mumbai"]},
    ], phone="9111100004")
    assert lead["name"] == "Priya Nair"
    assert lead.get("contact_name") == "Priya Nair"
    assert lead.get("city") == "Mumbai"


# ---- Case 5: no name field at all → fallback to phone ----
def test_no_name_fallback_to_phone(headers):
    lead = _fb_test(headers, [
        {"name": "phone_number", "values": ["9111100005"]},
        {"name": "email", "values": ["noname@example.com"]},
    ])
    # name should fall back to phone; contact_name may be empty
    assert lead["name"] == "9111100005", f"expected phone fallback, got {lead.get('name')}"
    assert not lead.get("contact_name"), f"contact_name should be empty, got {lead.get('contact_name')}"


# ---- Case 6: real custom question preserved + name parts NOT in custom ----
def test_custom_question_preserved(headers):
    lead = _fb_test(headers, [
        {"name": "first_name", "values": ["Neha"]},
        {"name": "last_name", "values": ["Verma"]},
        {"name": "want to consult an ivf expert at home", "values": ["yes"]},
    ], phone="9111100006")
    assert lead["name"] == "Neha Verma"
    custom = lead.get("custom") or {}
    # the real Q&A survives (key normalized) → look for a matching x_custom_ key with "consult"
    matching = [k for k in custom if "consult" in k]
    assert matching, f"expected consult custom field, got {list(custom.keys())}"
    # name parts absent
    assert not any(k.startswith("x_custom_first") or k.startswith("x_custom_last") for k in custom)


# ---- Case 7: regression — source, dates, assignment, endpoints ----
def test_regression_metadata(headers):
    lead = _fb_test(headers, [
        {"name": "full_name", "values": ["Regression Case"]},
    ], phone="9111100007")
    assert lead.get("source_lead") == "Meta Lead Ads"
    assert lead.get("create_date")
    assert lead.get("user_id"), "round-robin caller assignment missing"
    assert lead.get("facebook_lead") is True


def test_recent_leads_endpoint(headers):
    r = requests.get(f"{BASE_URL}/api/admin/facebook/recent-leads",
                     headers=headers, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "total" in data and "leads" in data
    assert isinstance(data["leads"], list)


def test_diagnose_endpoint(headers):
    r = requests.get(f"{BASE_URL}/api/admin/facebook/diagnose",
                     headers=headers, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "checks" in data


def test_invalid_signature_webhook_returns_401():
    # Requires configured settings (app_secret + page_access_token). If not configured
    # the endpoint returns 503 — accept that as environment reality, otherwise 401.
    r = requests.post(f"{BASE_URL}/api/webhooks/facebook",
                      headers={"X-Hub-Signature-256": "sha256=deadbeef",
                              "Content-Type": "application/json"},
                      data=b'{"entry":[]}', timeout=15)
    assert r.status_code in (401, 503), f"got {r.status_code} {r.text}"


def test_backend_healthy():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200
