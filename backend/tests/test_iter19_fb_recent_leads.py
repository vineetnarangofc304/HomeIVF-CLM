"""Iteration 19: verify GET /api/admin/facebook/recent-leads
and admin visibility regressions for Meta Lead Ads leads."""
import os
import time
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
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


# ---------- Recent-leads endpoint ----------
def test_recent_leads_requires_auth():
    r = requests.get(f"{BASE_URL}/api/admin/facebook/recent-leads", timeout=15)
    assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"


def test_recent_leads_shape_and_sort():
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/admin/facebook/recent-leads", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total" in data and isinstance(data["total"], int)
    assert "leads" in data and isinstance(data["leads"], list)
    assert data["total"] >= len(data["leads"])
    assert len(data["leads"]) <= 25
    ids = [l["id"] for l in data["leads"]]
    assert ids == sorted(ids, reverse=True), f"leads not sorted by id desc: {ids}"
    for l in data["leads"]:
        # required projected keys
        for k in ("id", "phone", "assigned_to"):
            assert k in l, f"missing {k} in {l}"
        # name OR contact_name should be present (either projection returns it)
        assert ("name" in l) or ("contact_name" in l)
        # assigned_to is either a user name (str) or 'Unassigned'
        assert isinstance(l["assigned_to"], str)


def test_recent_leads_only_facebook():
    """Verify each returned lead is actually a Facebook lead by inspecting via /api/leads/{id}."""
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/admin/facebook/recent-leads", timeout=20)
    assert r.status_code == 200
    leads = r.json()["leads"]
    if not leads:
        return  # nothing to check
    sample = leads[:3]
    for l in sample:
        rr = s.get(f"{BASE_URL}/api/leads/{l['id']}", timeout=15)
        # Some CRMs return 200 with full record; accept 200 only
        assert rr.status_code == 200, f"lead {l['id']} fetch failed: {rr.status_code}"
        body = rr.json()
        # facebook_lead True OR source_lead == Meta Lead Ads (either signal)
        assert body.get("facebook_lead") is True or body.get("source_lead") in (
            "Meta Lead Ads", "Facebook Lead Ads", "Facebook Lead Ads (test)"
        ), f"lead {l['id']} not a FB lead: fb={body.get('facebook_lead')} src={body.get('source_lead')}"


# ---------- Regression: FB test lead appears at top of admin /api/leads ----------
def test_fb_test_lead_appears_in_admin_list_and_by_source_filter():
    s = _admin_session()
    unique = f"IT19-{int(time.time())}"
    body = {
        "field_data": [
            {"name": "full_name", "values": [f"Iter19 Test {unique}"]},
            {"name": "phone_number", "values": ["+919999900019"]},
            {"name": "email", "values": [f"{unique.lower()}@example.com"]},
        ],
        "form_name": "Iter19 Form",
        "campaign_name": "Iter19 Campaign",
    }
    r = s.post(f"{BASE_URL}/api/admin/facebook/test", json=body, timeout=20)
    assert r.status_code == 200, r.text
    new_id = r.json()["lead_id"]

    # default admin list, sort=create_date desc → new lead should be near the top
    r2 = s.get(f"{BASE_URL}/api/leads", params={"page": 1, "page_size": 25}, timeout=20)
    assert r2.status_code == 200, r2.text
    payload = r2.json()
    items = payload.get("items") or payload.get("leads") or payload.get("results") or payload
    assert isinstance(items, list) and items, f"unexpected list payload: {str(payload)[:200]}"
    top_ids = [i.get("id") for i in items[:25]]
    assert new_id in top_ids, f"newly-created FB lead {new_id} not in top-25 of admin list: {top_ids[:10]}..."

    # source_lead filter
    r3 = s.get(f"{BASE_URL}/api/leads",
               params={"source_lead": "Meta Lead Ads", "page": 1, "page_size": 50},
               timeout=20)
    # Endpoint may return Meta Lead Ads OR Facebook Lead Ads (test) — try both if needed
    assert r3.status_code == 200, r3.text
    src_items = r3.json().get("items") or r3.json().get("leads") or []
    # Our test lead is created with source 'Facebook Lead Ads (test)', so also check it via that filter
    if new_id not in [i.get("id") for i in src_items]:
        r3b = s.get(f"{BASE_URL}/api/leads",
                    params={"source_lead": "Facebook Lead Ads (test)", "page": 1, "page_size": 50},
                    timeout=20)
        assert r3b.status_code == 200, r3b.text
        src_items = r3b.json().get("items") or r3b.json().get("leads") or []
    assert new_id in [i.get("id") for i in src_items], (
        f"FB test lead {new_id} not returned by source_lead filter"
    )

    # And it must now also appear in recent-leads (top since newest id)
    r4 = s.get(f"{BASE_URL}/api/admin/facebook/recent-leads", timeout=20)
    assert r4.status_code == 200
    top_recent = [l["id"] for l in r4.json()["leads"][:5]]
    assert new_id in top_recent, f"new FB lead {new_id} not in top-5 recent-leads: {top_recent}"


# ---------- Iter17/18 regressions ----------
def test_diagnose_still_has_five_checks_and_recent_deliveries():
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/admin/facebook/diagnose", timeout=25)
    assert r.status_code == 200, r.text
    data = r.json()
    names = [c.get("name") for c in data.get("checks", [])]
    assert "Access Token" in names
    assert "Token ↔ App match" in names
    assert "leads_retrieval permission" in names
    assert "Page subscribed to leagen".replace("agen", "agen") or True  # trivially true
    assert "Page subscribed to leadgen" in names
    assert "App leadgen webhook" in names
    assert "recent_webhook_deliveries" in data


def test_webhook_log_endpoint():
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/admin/facebook/webhook-log", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "count" in body and "logs" in body
    # no auth
    r2 = requests.get(f"{BASE_URL}/api/admin/facebook/webhook-log", timeout=15)
    assert r2.status_code in (401, 403)


def test_invalid_signature_webhook_rejected():
    r = requests.post(
        f"{BASE_URL}/api/webhooks/facebook",
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"},
        data=b'{"object":"page","entry":[]}',
        timeout=15,
    )
    assert r.status_code == 401, f"expected 401 got {r.status_code} {r.text[:200]}"
