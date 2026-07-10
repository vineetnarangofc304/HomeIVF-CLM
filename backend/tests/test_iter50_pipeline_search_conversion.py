"""Iteration 50 tests: pipeline/ozonetel buckets, index-friendly search, and conversion_page from website webhook."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER = {"email": "agent@homeivf.com", "password": "Agent@2026"}
WEBHOOK_TOKEN = "CryZ57P9BFonnFw8S87tqw"

created_lead_ids = []  # to report


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code} {r.text[:200]}"
    d = r.json()
    return d.get("access_token") or d.get("token")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN)}"}


@pytest.fixture(scope="module")
def caller_h():
    return {"Authorization": f"Bearer {_login(CALLER)}"}


def _get(headers, params):
    t0 = time.time()
    r = requests.get(f"{BASE_URL}/api/leads", headers=headers, params=params, timeout=30)
    return r, time.time() - t0


# --- Bucket: pipeline (excludes 200 raw Ozonetel) ---
def test_bucket_pipeline_fast(admin_h):
    r, e = _get(admin_h, {"bucket": "pipeline", "limit": 50, "page": 1})
    assert r.status_code == 200, r.text[:300]
    assert e < 3.0, f"pipeline slow: {e:.2f}s"
    d = r.json()
    total = d.get("total") or d.get("total_count") or 0
    items = d.get("items") or d.get("leads") or []
    assert 119000 <= total <= 121000, f"pipeline total unexpected: {total}"
    assert len(items) == 50
    print(f"pipeline total={total} {e:.2f}s")


def test_bucket_ozonetel(admin_h):
    r, e = _get(admin_h, {"bucket": "ozonetel", "limit": 50, "page": 1})
    assert r.status_code == 200, r.text[:300]
    assert e < 3.0, f"ozonetel slow: {e:.2f}s"
    d = r.json()
    total = d.get("total") or d.get("total_count") or 0
    assert total == 200, f"ozonetel total expected 200, got {total}"
    print(f"ozonetel total={total} {e:.2f}s")


# --- Search: phone digits exact ---
def test_search_phone_exact(admin_h):
    r, e = _get(admin_h, {"search": "9998887766", "limit": 50})
    assert r.status_code == 200, r.text[:300]
    assert e < 2.0, f"phone exact slow: {e:.2f}s"
    d = r.json()
    items = d.get("items") or d.get("leads") or []
    total = d.get("total") or d.get("total_count") or 0
    assert total == 1, f"expected 1, got {total}"
    assert items and items[0].get("name") == "Lead 650057", f"got {items[:1]}"
    print(f"phone exact total={total} {e:.2f}s")


def test_search_phone_prefix(admin_h):
    r, e = _get(admin_h, {"search": "99988", "limit": 50})
    assert r.status_code == 200, r.text[:300]
    assert e < 2.0, f"phone prefix slow: {e:.2f}s"
    d = r.json()
    items = d.get("items") or d.get("leads") or []
    names = [it.get("name") for it in items]
    assert "Lead 650057" in names, f"Lead 650057 not in {names[:10]}"
    print(f"phone prefix {e:.2f}s hits={len(items)}")


# --- Search: name prefix ---
def test_search_name_prefix(admin_h):
    r, e = _get(admin_h, {"search": "Lead 6500", "limit": 50})
    assert r.status_code == 200, r.text[:300]
    assert e < 5.0, f"name prefix slow: {e:.2f}s"
    d = r.json()
    items = d.get("items") or d.get("leads") or []
    assert items, "no results for 'Lead 6500'"
    # Query has digits (6500) so backend also ORs a phone_digits prefix; either
    # name-startswith or phone-startswith is acceptable.
    name_prefix_hits = [it for it in items if (it.get("name") or "").startswith("Lead 6500")]
    assert name_prefix_hits, f"no name-prefix hits in first page: {[it.get('name') for it in items[:5]]}"
    print(f"name prefix {e:.2f}s hits={len(items)}")


def test_search_name_midword_no_match(admin_h):
    # starts-with means a mid-word substring shouldn't match — e.g. 'ead 65'
    r, e = _get(admin_h, {"search": "ead 65", "limit": 50})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    items = d.get("items") or d.get("leads") or []
    # Should not include any Lead 65XXXX
    hits = [it for it in items if (it.get("name") or "").startswith("Lead 65")]
    assert not hits, f"mid-word substring should not match Lead 65*: {[h.get('name') for h in hits][:5]}"
    print(f"midword no-match total={d.get('total')} {e:.2f}s")


# --- Pagination on pipeline bucket ---
def test_pipeline_pagination(admin_h):
    r2, e2 = _get(admin_h, {"bucket": "pipeline", "page": 2, "limit": 50})
    r3, e3 = _get(admin_h, {"bucket": "pipeline", "page": 3, "limit": 50})
    assert r2.status_code == 200 and r3.status_code == 200
    ids2 = {it.get("id") for it in (r2.json().get("items") or r2.json().get("leads") or [])}
    ids3 = {it.get("id") for it in (r3.json().get("items") or r3.json().get("leads") or [])}
    assert ids2 and ids3 and ids2.isdisjoint(ids3)
    print(f"pipeline p2 {e2:.2f}s p3 {e3:.2f}s")


# --- Caller scope ---
def test_caller_scope(caller_h):
    r, e = _get(caller_h, {"page": 1, "limit": 50})
    assert r.status_code == 200, r.text[:300]
    assert e < 3.0, f"caller slow: {e:.2f}s"
    d = r.json()
    total = d.get("total") or d.get("total_count") or 0
    assert 0 < total < 120000, f"caller total unreasonable: {total}"
    print(f"caller total={total} {e:.2f}s")


# --- No regression: filters ---
@pytest.mark.parametrize("params", [
    {"source_lead": "Website"},
    {"lead_stage": "Contacted"},
])
def test_filters_no_regression(admin_h, params):
    r, e = _get(admin_h, {**params, "page": 1, "limit": 50})
    assert r.status_code == 200, r.text[:300]
    assert e < 3.0, f"{params} slow: {e:.2f}s"
    print(f"{params} {e:.2f}s")


# --- Conversion Page via website webhook ---
def _post_webhook(payload):
    r = requests.post(
        f"{BASE_URL}/api/webhook/lead/{WEBHOOK_TOKEN}",
        json=payload,
        timeout=15,
    )
    return r


def _get_lead(admin_h, lid):
    r = requests.get(f"{BASE_URL}/api/leads/{lid}", headers=admin_h, timeout=15)
    return r


@pytest.mark.parametrize("payload_key,payload_val", [
    ("page_url", "https://homeivf.com/contact"),
    ("page_name", "IVF-Landing-Page"),
    ("form_name", "Enquiry-Form"),
])
def test_webhook_conversion_page(admin_h, payload_key, payload_val):
    body = {"name": f"WT {payload_key}", "phone": f"97000{abs(hash(payload_key)) % 100000:05d}", payload_key: payload_val}
    r = _post_webhook(body)
    assert r.status_code == 200, f"webhook status {r.status_code}: {r.text[:300]}"
    d = r.json()
    assert d.get("ok") is True, f"ok not true: {d}"
    lid = d.get("lead_id") or d.get("id")
    assert lid, f"no lead_id in {d}"
    created_lead_ids.append(lid)
    # fetch and verify
    time.sleep(0.3)
    g = _get_lead(admin_h, lid)
    assert g.status_code == 200, f"get lead {lid}: {g.status_code} {g.text[:200]}"
    lead = g.json()
    assert lead.get("conversion_page") == payload_val, f"conversion_page mismatch: {lead.get('conversion_page')} vs {payload_val}"
    assert lead.get("source_lead") == "Website", f"source_lead should be Website, got {lead.get('source_lead')}"
    print(f"webhook {payload_key} -> lead {lid} conversion_page={lead.get('conversion_page')}")


def test_report_created_ids():
    print(f"CREATED_LEAD_IDS_FOR_CLEANUP: {created_lead_ids}")
