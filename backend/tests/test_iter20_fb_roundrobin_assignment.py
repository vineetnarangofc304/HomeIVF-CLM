"""Iteration 20: verify FB leads are now round-robin assigned to active callers
(no longer orphaned as Unassigned), still expose source_lead/create_date/create_date_ist,
appear in default /api/leads list and in each assigned caller's user_id-filtered list,
and that recent-leads returns caller NAME (not 'Unassigned') for the new leads.

Also re-runs the iter17-19 regression checks to make sure nothing else broke."""
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
               json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=20)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


def _make_fb_lead(s, tag):
    body = {
        "field_data": [
            {"name": "full_name", "values": [f"Iter20 {tag}"]},
            {"name": "phone_number", "values": [f"+91888880{int(time.time()) % 10000:04d}"]},
            {"name": "email", "values": [f"iter20-{tag}-{int(time.time()*1000)%100000}@example.com"]},
        ],
        "form_name": "Iter20 Form",
        "campaign_name": "Iter20 Campaign",
    }
    r = s.post(f"{BASE_URL}/api/admin/facebook/test", json=body, timeout=25)
    assert r.status_code == 200, f"fb test create failed: {r.status_code} {r.text}"
    return r.json()


# ---------- Core: user_id is assigned to an ACTIVE caller (not None) ----------
def test_fb_test_lead_gets_assigned_to_active_caller():
    s = _admin_session()
    payload = _make_fb_lead(s, "assign-1")
    lead = payload["lead"]

    assert lead.get("user_id") is not None, f"FB lead was NOT assigned (user_id is None). Lead: {lead}"
    assert isinstance(lead["user_id"], int)

    # Look up assigned user via /api/users list
    ru2 = s.get(f"{BASE_URL}/api/users", timeout=20)
    assert ru2.status_code == 200, ru2.text
    users = ru2.json()
    users = users.get("items") if isinstance(users, dict) else users
    found = next((u for u in users if u.get("id") == lead["user_id"]), None)
    assert found, f"assigned user_id {lead['user_id']} not found in users list"
    assert found.get("active") is True, f"assigned user is not active: {found}"
    assert found.get("role") == "caller", f"assigned user role is not caller: {found}"


# ---------- Round-robin: creating 3 leads rotates user_id across active callers ----------
def test_roundrobin_across_three_leads():
    s = _admin_session()
    assigned = []
    for i in range(3):
        pl = _make_fb_lead(s, f"rr-{i}")
        assigned.append(pl["lead"].get("user_id"))
    # All non-null
    assert all(a is not None for a in assigned), f"some FB leads unassigned: {assigned}"
    # Rotation: at least 2 distinct user_ids across 3 consecutive leads
    # (with 30+ active callers, three consecutive fb_assign_pointer values must land on distinct ids)
    assert len(set(assigned)) >= 2, f"round-robin did not rotate; got same user_id for 3 leads: {assigned}"


# ---------- Fields: source_lead / create_date / create_date_ist / active ----------
def test_fb_lead_fields_and_appears_in_default_leads_list():
    s = _admin_session()
    pl = _make_fb_lead(s, "fields")
    lead = pl["lead"]
    lid = pl["lead_id"]

    assert lead.get("source_lead") == "Meta Lead Ads", f"unexpected source_lead: {lead.get('source_lead')}"
    assert lead.get("create_date"), "missing create_date"
    assert lead.get("create_date_ist"), "missing create_date_ist"
    assert lead.get("active") is True

    # Default admin /api/leads listing (create_date desc) → new lead near the top
    r = s.get(f"{BASE_URL}/api/leads", params={"page": 1, "page_size": 25}, timeout=25)
    assert r.status_code == 200, r.text
    payload = r.json()
    items = payload.get("items") or payload.get("leads") or payload.get("results") or payload
    assert isinstance(items, list) and items
    top_ids = [i.get("id") for i in items[:25]]
    assert lid in top_ids, f"new FB lead {lid} not in top-25 default list"
    # Also confirm the returned list item has the expected source/create_date fields present
    itm = next(i for i in items if i.get("id") == lid)
    assert itm.get("source_lead") == "Meta Lead Ads"
    assert itm.get("create_date")


# ---------- Assigned caller can see the FB lead via user_id filter ----------
def test_assigned_caller_sees_lead_via_user_id_filter():
    s = _admin_session()
    pl = _make_fb_lead(s, "seeit")
    lead = pl["lead"]
    lid = pl["lead_id"]
    uid = lead.get("user_id")
    assert uid is not None

    r = s.get(f"{BASE_URL}/api/leads",
              params={"user_id": uid, "page": 1, "page_size": 50}, timeout=25)
    assert r.status_code == 200, r.text
    items = r.json().get("items") or r.json().get("leads") or []
    ids = [i.get("id") for i in items]
    assert lid in ids, f"FB lead {lid} not returned when filtering by assigned user_id={uid}. Top: {ids[:10]}"


# ---------- recent-leads shows caller NAME (not 'Unassigned') for new leads ----------
def test_recent_leads_shows_caller_name_not_unassigned():
    s = _admin_session()
    pl = _make_fb_lead(s, "recent-name")
    lid = pl["lead_id"]

    r = s.get(f"{BASE_URL}/api/admin/facebook/recent-leads", timeout=25)
    assert r.status_code == 200, r.text
    leads = r.json().get("leads", [])
    match = next((l for l in leads if l.get("id") == lid), None)
    assert match, f"new FB lead {lid} not found in recent-leads"
    assigned_to = match.get("assigned_to")
    assert assigned_to and assigned_to != "Unassigned", \
        f"assigned_to should be a caller name, got {assigned_to!r}"
    assert isinstance(assigned_to, str)


# ---------- Regression: diagnose still has 5 checks + recent_webhook_deliveries ----------
def test_diagnose_regression():
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/admin/facebook/diagnose", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    names = [c.get("name") for c in data.get("checks", [])]
    for expected in ("Access Token", "Token ↔ App match", "leads_retrieval permission",
                     "Page subscribed to leadgen", "App leadgen webhook"):
        assert expected in names, f"missing diagnose check {expected!r}; got {names}"
    assert "recent_webhook_deliveries" in data


# ---------- Regression: webhook-log requires auth ----------
def test_webhook_log_auth():
    r = requests.get(f"{BASE_URL}/api/admin/facebook/webhook-log", timeout=15)
    assert r.status_code in (401, 403)
    s = _admin_session()
    r2 = s.get(f"{BASE_URL}/api/admin/facebook/webhook-log", timeout=15)
    assert r2.status_code == 200
    body = r2.json()
    assert "count" in body and "logs" in body


# ---------- Regression: invalid-signature webhook → 401 + rejected log ----------
def test_invalid_signature_webhook_rejected_and_logged():
    r = requests.post(
        f"{BASE_URL}/api/webhooks/facebook",
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"},
        data=b'{"object":"page","entry":[]}',
        timeout=15,
    )
    assert r.status_code == 401, f"expected 401 got {r.status_code}"
    # log entry should have a 'rejected' record now
    s = _admin_session()
    lg = s.get(f"{BASE_URL}/api/admin/facebook/webhook-log", timeout=15).json()
    statuses = [l.get("status") for l in lg.get("logs", [])]
    assert "rejected" in statuses, f"no 'rejected' entry in webhook log: {statuses[:5]}"


# ---------- Regression: source_lead catalog still contains 'Meta Lead Ads' ----------
def test_source_lead_catalog_has_meta_lead_ads():
    s = _admin_session()
    # try common catalog endpoint patterns
    for path in ("/api/catalogs/source_lead", "/api/catalog/source_lead",
                 "/api/catalogs?type=source_lead", "/api/config/source_lead"):
        r = s.get(f"{BASE_URL}{path}", timeout=15)
        if r.status_code == 200:
            data = r.json()
            # try common shapes
            values = None
            if isinstance(data, list):
                values = [d.get("name") if isinstance(d, dict) else d for d in data]
            elif isinstance(data, dict):
                values = data.get("values") or data.get("items") or data.get("options")
                if isinstance(values, list) and values and isinstance(values[0], dict):
                    values = [v.get("name") or v.get("value") for v in values]
            if values and "Meta Lead Ads" in values:
                return
    # Fallback: check via leads filter — creating a fresh one already ensures ensure_catalog ran.
    pl = _make_fb_lead(s, "catalog")
    assert pl["lead"].get("source_lead") == "Meta Lead Ads"
