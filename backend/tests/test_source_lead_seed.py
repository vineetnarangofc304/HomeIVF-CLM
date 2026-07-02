"""Tests for Meta Lead Ads source_lead catalog seed fix."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to frontend env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASSWORD = "HomeIVF@2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"No token in response: {data}"
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_catalogs_includes_meta_lead_ads(headers):
    r = requests.get(f"{BASE_URL}/api/catalogs", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    # data may be dict grouped by type or list
    source_leads = data.get("source_lead") if isinstance(data, dict) else [
        c for c in data if c.get("type") == "source_lead"
    ]
    assert source_leads, f"No source_lead entries: {data}"
    names = [c["name"] for c in source_leads]
    assert "Meta Lead Ads" in names, f"'Meta Lead Ads' missing. Got: {names}"


def test_catalogs_preserves_existing_sources(headers):
    r = requests.get(f"{BASE_URL}/api/catalogs", headers=headers)
    assert r.status_code == 200
    data = r.json()
    source_leads = data.get("source_lead") if isinstance(data, dict) else [
        c for c in data if c.get("type") == "source_lead"
    ]
    names = [c["name"] for c in source_leads]
    for expected in ["landing_page", "chatbot", "website", "App", "Callback_Request"]:
        assert expected in names, f"Missing existing source '{expected}'. Got: {names}"


def test_no_duplicate_meta_lead_ads(headers):
    r = requests.get(f"{BASE_URL}/api/catalogs", headers=headers)
    data = r.json()
    source_leads = data.get("source_lead") if isinstance(data, dict) else [
        c for c in data if c.get("type") == "source_lead"
    ]
    count = sum(1 for c in source_leads if c["name"] == "Meta Lead Ads")
    assert count == 1, f"Expected 1 'Meta Lead Ads', got {count}"


def test_create_source_lead_catalog_still_works(headers):
    payload = {"name": "TEST_source_pytest", "active": True}
    r = requests.post(f"{BASE_URL}/api/catalogs/source_lead",
                      json=payload, headers=headers)
    assert r.status_code in (200, 201), f"{r.status_code}: {r.text}"
    body = r.json()
    assert body.get("name") == "TEST_source_pytest"

    # verify in list
    r2 = requests.get(f"{BASE_URL}/api/catalogs", headers=headers)
    data = r2.json()
    source_leads = data.get("source_lead") if isinstance(data, dict) else [
        c for c in data if c.get("type") == "source_lead"
    ]
    names = [c["name"] for c in source_leads]
    assert "TEST_source_pytest" in names

    # cleanup
    created_id = body.get("id")
    if created_id is not None:
        requests.delete(f"{BASE_URL}/api/catalogs/source_lead/{created_id}",
                        headers=headers)
