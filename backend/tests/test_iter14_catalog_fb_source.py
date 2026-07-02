"""Iteration 14 tests: catalog create fix + FB source_lead auto-register."""
import os
import time
import requests
import pytest

def _load_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.strip().startswith("REACT_APP_BACKEND_URL="):
                        v = line.strip().split("=", 1)[1]
                        break
        except Exception:
            pass
    assert v, "REACT_APP_BACKEND_URL missing"
    return v.rstrip("/")


BASE_URL = _load_url()
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASS = "HomeIVF@2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


UNIQ = str(int(time.time()))


# ---- Catalog create fix ----
def test_create_catalog_source_lead(h):
    name = f"QA Source One {UNIQ}"
    r = requests.post(f"{API}/catalogs/source_lead", json={"name": name}, headers=h, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("type") == "source_lead"
    assert d.get("name") == name
    assert "id" in d
    assert d.get("active") in (True, 1, None) or d.get("active") is True

    # Idempotency: second create returns the same doc, no 500, no duplicate
    r2 = requests.post(f"{API}/catalogs/source_lead", json={"name": name}, headers=h, timeout=30)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2.get("id") == d.get("id"), f"Expected idempotent same id, got {d2} vs {d}"


def test_create_catalog_tag(h):
    name = f"QA Tag {UNIQ}"
    r = requests.post(f"{API}/catalogs/tag", json={"name": name}, headers=h, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("type") == "tag"
    assert d.get("name") == name


# ---- FB source_lead auto-register via ensure_catalog ----
def test_fb_test_creates_lead_meta_source_and_registers_catalog(h):
    payload = {
        "field_data": [
            {"name": "full_name", "values": [f"QA Source Lead {UNIQ}"]},
            {"name": "phone_number", "values": ["9800012345"]},
        ],
        "leadgen_id": f"QA_SRC_{UNIQ}",
    }
    r = requests.post(f"{API}/admin/facebook/test", json=payload, headers=h, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    # Common shapes: {ok:true, lead:{...}} or the lead itself
    lead = body.get("lead") or body
    src = lead.get("source_lead") if isinstance(lead, dict) else None
    if src is None:
        # Fallback: query by contact
        gl = requests.get(f"{API}/leads", params={"search": f"QA Source Lead {UNIQ}"}, headers=h, timeout=30)
        assert gl.status_code == 200
        items = gl.json().get("items") or gl.json()
        assert items, f"Lead not found after FB test: {body}"
        src = items[0].get("source_lead")
    assert src == "Meta Lead Ads", f"Expected source_lead='Meta Lead Ads', got {src}. body={body}"

    # Now catalogs must contain 'Meta Lead Ads' under source_lead
    cat = requests.get(f"{API}/catalogs", headers=h, timeout=30)
    assert cat.status_code == 200
    cj = cat.json()
    # Response could be dict of lists, or list of docs
    names = []
    if isinstance(cj, dict) and "source_lead" in cj:
        names = [x.get("name") if isinstance(x, dict) else x for x in cj["source_lead"]]
    elif isinstance(cj, list):
        names = [x.get("name") for x in cj if x.get("type") == "source_lead"]
    else:
        # try filtered endpoint
        cat2 = requests.get(f"{API}/catalogs/source_lead", headers=h, timeout=30)
        if cat2.status_code == 200:
            j2 = cat2.json()
            names = [x.get("name") for x in (j2 if isinstance(j2, list) else j2.get("items", []))]
    assert "Meta Lead Ads" in names, f"'Meta Lead Ads' not found in source_lead catalog: {names}"


def test_leads_filter_by_meta_source(h):
    r = requests.get(f"{API}/leads", params={"source_lead": "Meta Lead Ads"}, headers=h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    items = body.get("items") if isinstance(body, dict) else body
    assert isinstance(items, list) and len(items) >= 1
    # At least one lead with our QA contact
    names = [it.get("contact_name") for it in items]
    assert any(f"QA Source Lead {UNIQ}" in (n or "") for n in names), f"QA lead not found in filter: {names[:5]}"


def test_fb_attribution_mapping(h):
    payload = {
        "field_data": [
            {"name": "full_name", "values": [f"QA Attr Lead {UNIQ}"]},
            {"name": "phone_number", "values": ["9800099999"]},
        ],
        "leadgen_id": f"QA_ATTR_{UNIQ}",
        "campaign_name": "CampaignQA",
        "adset_name": "AdsetQA",
        "ad_name": "AdQA",
        "form_name": "FormQA",
    }
    r = requests.post(f"{API}/admin/facebook/test", json=payload, headers=h, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    lead = body.get("lead") or body
    if not isinstance(lead, dict) or "campaign_name" not in lead:
        gl = requests.get(f"{API}/leads", params={"search": f"QA Attr Lead {UNIQ}"}, headers=h, timeout=30)
        items = gl.json().get("items") or gl.json()
        assert items
        lead = items[0]
    assert lead.get("campaign_name") == "CampaignQA", lead
    assert lead.get("ads_campaign_name") in ("AdsetQA", "CampaignQA"), lead
    assert lead.get("ads_name") == "AdQA", lead


# ---- Regression FB diagnose + register-webhook ----
def test_fb_diagnose_ok(h):
    r = requests.get(f"{API}/admin/facebook/diagnose", headers=h, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    checks = body.get("checks") or body
    # Expect all 3 checks ok=true
    if isinstance(checks, list):
        for c in checks:
            assert c.get("ok") is True, f"Check failed: {c}"
        assert len(checks) >= 3
    elif isinstance(checks, dict):
        for k, v in checks.items():
            ok = v.get("ok") if isinstance(v, dict) else v
            assert ok is True, f"{k} not ok: {v}"


def test_fb_register_webhook(h):
    cb = f"{BASE_URL}/api/webhooks/facebook"
    r = requests.post(f"{API}/admin/facebook/register-webhook", json={"callback_url": cb}, headers=h, timeout=60)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True, r.text
