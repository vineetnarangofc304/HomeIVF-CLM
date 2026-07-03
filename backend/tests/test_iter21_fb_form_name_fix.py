"""Iteration 21: verify PRODUCTION BUG FIX for Meta Graph API error #100 —
'Tried accessing nonexisting field (form_name)'.

The webhook fetch previously requested field 'form_name' on the leadgen node,
which is not a valid field → the whole fetch failed → 0 leads ever created.

Fix: removed 'form_name' from the leadgen fields string in
/app/backend/routes/facebook.py fb_webhook(); form name is now fetched via a
separate GET /{form_id}?fields=name and injected as lead['form_name'] before
_map_and_create_lead runs.

Preview cannot exercise the live Graph fetch — so we assert:
 (1) the fields string in the source no longer contains 'form_name' (and matches
     the exact expected list),
 (2) a separate 'name' fetch on {form_id} is present in the webhook code path,
 (3) POST /api/admin/facebook/test (which bypasses Graph) still creates a lead
     with fb_form_name populated, source_lead='Meta Lead Ads', assigned to an
     active caller, and appears near the top of default /api/leads list,
 (4) regression: recent-leads / webhook-log / diagnose / invalid-signature all
     still behave, backend is healthy.
"""
import os
import re
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
FB_ROUTE = "/app/backend/routes/facebook.py"

EXPECTED_FIELDS = (
    "id,created_time,field_data,ad_id,ad_name,adset_id,adset_name,"
    "campaign_id,campaign_name,form_id,platform,is_organic"
)


def _admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=20)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


def _make_fb_test_lead(s, tag, form_name="Iter21 Verify Form"):
    body = {
        "field_data": [
            {"name": "full_name", "values": [f"Iter21 {tag}"]},
            {"name": "phone_number", "values": [f"+91777770{int(time.time()) % 10000:04d}"]},
            {"name": "email", "values": [f"iter21-{tag}-{int(time.time()*1000)%100000}@example.com"]},
        ],
        "form_name": form_name,
        "campaign_name": "Iter21 Campaign",
    }
    r = s.post(f"{BASE_URL}/api/admin/facebook/test", json=body, timeout=25)
    assert r.status_code == 200, f"fb test create failed: {r.status_code} {r.text}"
    return r.json()


# ---------- (1) Source no longer requests 'form_name' on the leadgen node ----------
def test_webhook_fields_string_no_form_name():
    with open(FB_ROUTE) as f:
        src = f.read()

    # locate the fields= assignment inside fb_webhook — should be the exact expected list.
    assert f'"fields": "{EXPECTED_FIELDS}"' in src, (
        "leadgen fields string does not match the expected list "
        f"(should be {EXPECTED_FIELDS!r})"
    )

    # No 'form_name' in any fields= parameter passed to the leadgen graph call.
    # Find every quoted fields=... value and ensure none of them include form_name
    # as a requested field (form_name is a valid dict key later, but must NOT be
    # inside the comma-separated fields list sent to Graph).
    for m in re.finditer(r'"fields"\s*:\s*"([^"]+)"', src):
        fields_val = m.group(1)
        parts = [p.strip() for p in fields_val.split(",")]
        assert "form_name" not in parts, (
            f"'form_name' still requested in a Graph fields string: {fields_val!r}"
        )


# ---------- (2) A separate {form_id}?fields=name fetch is present ----------
def test_webhook_fetches_form_name_separately():
    with open(FB_ROUTE) as f:
        src = f.read()
    # graph call to {form_id} with fields=name
    assert "form_id" in src and 'fields": "name"' in src, (
        "expected a separate GET on /{form_id}?fields=name to fetch the form name"
    )
    # And it must be injected as lead['form_name'] before mapping runs.
    assert 'lead["form_name"]' in src or "lead['form_name']" in src, (
        "form_name should be injected into the leadgen dict before _map_and_create_lead"
    )


# ---------- (3) Test endpoint still creates a lead with fb_form_name mapped ----------
def test_fb_test_endpoint_maps_form_name_and_assigns_caller():
    s = _admin_session()
    pl = _make_fb_test_lead(s, "core", form_name="Iter21 Form ABC")
    lead = pl["lead"]
    lid = pl.get("lead_id")

    assert lid, f"missing lead_id in response: {pl}"
    assert lead.get("fb_form_name") == "Iter21 Form ABC", (
        f"fb_form_name not mapped from form_name input; got {lead.get('fb_form_name')!r}"
    )
    assert lead.get("source_lead") == "Meta Lead Ads"
    assert lead.get("create_date")
    assert lead.get("active") is True

    # Caller assignment (round-robin) — user_id must point to an ACTIVE caller
    uid = lead.get("user_id")
    assert uid is not None, f"FB lead was NOT assigned (user_id is None): {lead}"
    users = s.get(f"{BASE_URL}/api/users", timeout=20).json()
    users = users.get("items") if isinstance(users, dict) else users
    assigned = next((u for u in users if u.get("id") == uid), None)
    assert assigned, f"assigned user_id {uid} not present in /api/users"
    assert assigned.get("active") is True and assigned.get("role") == "caller", \
        f"assigned user not an active caller: {assigned}"


# ---------- (3b) The created lead appears near top of default /api/leads ----------
def test_new_fb_lead_appears_in_default_leads_list():
    s = _admin_session()
    pl = _make_fb_test_lead(s, "top", form_name="Iter21 Form Top")
    lid = pl["lead_id"]

    r = s.get(f"{BASE_URL}/api/leads", params={"page": 1, "page_size": 25}, timeout=25)
    assert r.status_code == 200, r.text
    payload = r.json()
    items = payload.get("items") or payload.get("leads") or payload.get("results") or payload
    assert isinstance(items, list) and items
    top_ids = [i.get("id") for i in items[:25]]
    assert lid in top_ids, f"new FB lead {lid} not in top-25 default list (create_date desc)"
    itm = next(i for i in items if i.get("id") == lid)
    assert itm.get("source_lead") == "Meta Lead Ads"
    assert itm.get("create_date")


# ---------- (4) Backend healthy: no import/syntax errors after the change ----------
def test_backend_healthy():
    # /api/auth/login already tested — but hit an unauthenticated route too.
    # Any 2xx/4xx (not 5xx) confirms process is up.
    r = requests.get(f"{BASE_URL}/api/health", timeout=10)
    if r.status_code == 404:
        # Fallback: login is a reliable liveness probe
        r2 = requests.post(f"{BASE_URL}/api/auth/login",
                           json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=15)
        assert r2.status_code == 200, f"backend unhealthy: {r2.status_code} {r2.text}"
    else:
        assert r.status_code < 500, f"backend unhealthy: {r.status_code}"


# ---------- Regression: invalid-signature webhook → 401 + 'rejected' log ----------
def test_invalid_signature_webhook_rejected_and_logged():
    r = requests.post(
        f"{BASE_URL}/api/webhooks/facebook",
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"},
        data=b'{"object":"page","entry":[]}',
        timeout=15,
    )
    assert r.status_code == 401, f"expected 401 got {r.status_code}: {r.text}"
    s = _admin_session()
    lg = s.get(f"{BASE_URL}/api/admin/facebook/webhook-log", timeout=15).json()
    assert "count" in lg and "logs" in lg
    statuses = [l.get("status") for l in lg.get("logs", [])]
    assert "rejected" in statuses, f"no 'rejected' entry in webhook log: {statuses[:5]}"


# ---------- Regression: recent-leads shape + assigned_to for new lead ----------
def test_recent_leads_returns_shape_and_assigned_name():
    s = _admin_session()
    pl = _make_fb_test_lead(s, "recent", form_name="Iter21 Recent")
    lid = pl["lead_id"]

    r = s.get(f"{BASE_URL}/api/admin/facebook/recent-leads", timeout=25)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body and "leads" in body
    assert isinstance(body["leads"], list)
    match = next((l for l in body["leads"] if l.get("id") == lid), None)
    assert match, f"new FB lead {lid} not in recent-leads"
    a = match.get("assigned_to")
    assert a and a != "Unassigned" and isinstance(a, str), \
        f"assigned_to should be a caller name, got {a!r}"


# ---------- Regression: diagnose still returns 5 checks ----------
def test_diagnose_regression():
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/admin/facebook/diagnose", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    names = [c.get("name") for c in data.get("checks", [])]
    for expected in ("Access Token", "Token ↔ App match", "leads_retrieval permission",
                     "Page subscribed to leadgen", "App leadgen webhook"):
        assert expected in names, f"missing diagnose check {expected!r}; got {names}"
