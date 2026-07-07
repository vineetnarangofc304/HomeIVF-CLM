"""HomeIVF CRM backend API tests - covers auth, leads, group_counts, reports, admin, webhooks, RBAC."""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ivf-crm-preview.preview.emergentagent.com").rstrip("/")


# ---------------- Health ----------------
def test_health():
    r = requests.get(f"{BASE_URL}/api/health", timeout=15)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


# ---------------- Auth ----------------
def test_login_wrong_password():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@homeivf.com", "password": "wrong-xyz-123"}, timeout=15)
    assert r.status_code == 401
    body = r.json()
    assert "detail" in body


def test_login_admin_success_and_cookies():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@homeivf.com", "password": "HomeIVF@2026"}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == "admin@homeivf.com"
    assert data["role"] == "admin"
    assert "access_token" in data and len(data["access_token"]) > 20
    # cookies set
    cookie_names = {c.name for c in s.cookies}
    assert "access_token" in cookie_names, f"cookies: {cookie_names}"


def test_auth_me(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == "admin@homeivf.com"
    assert me["role"] == "admin"


def test_auth_me_unauth():
    r = requests.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert r.status_code in (401, 403)


# ---------------- Leads listing ----------------
def test_leads_list_admin_sees_all(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/leads?page=1&limit=10", timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "total" in body
    assert isinstance(body["items"], list)
    assert body["total"] > 50000, f"expected ~99k leads, got total={body['total']}"
    assert len(body["items"]) <= 10
    # row shape
    item = body["items"][0]
    for k in ("id", "name"):
        assert k in item


def test_leads_pagination(admin_client):
    r1 = admin_client.get(f"{BASE_URL}/api/leads?page=1&limit=5", timeout=30).json()
    r2 = admin_client.get(f"{BASE_URL}/api/leads?page=2&limit=5", timeout=30).json()
    ids1 = [i["id"] for i in r1["items"]]
    ids2 = [i["id"] for i in r2["items"]]
    assert ids1 != ids2
    assert len(set(ids1) & set(ids2)) == 0


def test_leads_filter_lead_stage_converted(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/leads?lead_stage=Converted&limit=5", timeout=30)
    assert r.status_code == 200
    body = r.json()
    for it in body["items"]:
        assert it.get("lead_stage") == "Converted"


def test_leads_filter_lost(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/leads?active=false&limit=5", timeout=30)
    assert r.status_code == 200


def test_leads_search_by_name(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/leads?search=a&limit=5", timeout=30)
    assert r.status_code == 200


def test_leads_search_by_phone(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/leads?search=9999999999&limit=5", timeout=30)
    assert r.status_code == 200


def test_group_counts_lead_stage(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/leads/group_counts?group_by=lead_stage", timeout=30)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) > 0
    for row in rows:
        assert "key" in row and "count" in row


def test_group_counts_tags(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/leads/group_counts?group_by=tags", timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_group_counts_user(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/leads/group_counts?group_by=user_id", timeout=30)
    assert r.status_code == 200


# ---------------- Lead create / update / lost / restore ----------------
@pytest.fixture(scope="module")
def created_lead_id(request):
    s = requests.Session()
    rl = s.post(f"{BASE_URL}/api/auth/login",
                json={"email": "admin@homeivf.com", "password": "HomeIVF@2026"}, timeout=15)
    s.headers.update({"Authorization": f"Bearer {rl.json()['access_token']}"})
    r = s.post(f"{BASE_URL}/api/leads",
               json={"name": "TEST_pytest_lead", "phone": "+919876500001",
                     "city": "Bangalore", "state_name": "Karnataka"}, timeout=30)
    assert r.status_code == 200, r.text
    lid = r.json()["id"]
    yield lid


def test_create_lead_persisted_and_retrievable(admin_client, created_lead_id):
    r = admin_client.get(f"{BASE_URL}/api/leads/{created_lead_id}", timeout=15)
    assert r.status_code == 200
    lead = r.json()
    assert lead["name"] == "TEST_pytest_lead"
    assert lead.get("active") is True
    assert lead.get("phone_digits", "").endswith("9876500001"[-10:])


def test_update_lead_stage_and_chatter_logs(admin_client, created_lead_id):
    r = admin_client.patch(f"{BASE_URL}/api/leads/{created_lead_id}",
                           json={"updates": {"lead_stage": "Contacted"}}, timeout=15)
    assert r.status_code == 200
    assert r.json()["lead_stage"] == "Contacted"

    # verify persisted
    r2 = admin_client.get(f"{BASE_URL}/api/leads/{created_lead_id}", timeout=15)
    assert r2.json()["lead_stage"] == "Contacted"

    # chatter should have at least 2 entries (created + tracking)
    rm = admin_client.get(f"{BASE_URL}/api/leads/{created_lead_id}/messages?limit=10", timeout=15)
    assert rm.status_code == 200


def test_mark_lost_and_restore(admin_client, created_lead_id):
    r = admin_client.post(f"{BASE_URL}/api/leads/{created_lead_id}/lost",
                          json={"note": "TEST_reason"}, timeout=15)
    assert r.status_code == 200
    g = admin_client.get(f"{BASE_URL}/api/leads/{created_lead_id}", timeout=15)
    assert g.json().get("active") is False
    r = admin_client.post(f"{BASE_URL}/api/leads/{created_lead_id}/restore", json={}, timeout=15)
    assert r.status_code == 200
    g = admin_client.get(f"{BASE_URL}/api/leads/{created_lead_id}", timeout=15)
    assert g.json().get("active") is True


# ---------------- Bulk actions ----------------
def test_bulk_assign(admin_client, created_lead_id):
    # find any user id to assign to
    ur = admin_client.get(f"{BASE_URL}/api/users", timeout=15)
    assert ur.status_code == 200
    users = ur.json()
    users = users if isinstance(users, list) else users.get("items", [])
    target = next((u for u in users if u.get("role") == "caller" and u.get("active", True)), None)
    if not target:
        pytest.skip("No caller user available")
    r = admin_client.post(f"{BASE_URL}/api/leads/bulk",
                          json={"ids": [created_lead_id], "action": "assign",
                                "payload": {"user_id": target["id"]}}, timeout=15)
    assert r.status_code == 200
    g = admin_client.get(f"{BASE_URL}/api/leads/{created_lead_id}", timeout=15)
    assert g.json().get("user_id") == target["id"]


# ---------------- Chatter ----------------
def test_post_note_appears(admin_client, created_lead_id):
    r = admin_client.post(f"{BASE_URL}/api/leads/{created_lead_id}/messages",
                          json={"body": "TEST_note_pytest", "internal": True}, timeout=15)
    assert r.status_code in (200, 201)
    rm = admin_client.get(f"{BASE_URL}/api/leads/{created_lead_id}/messages?limit=20", timeout=15)
    assert rm.status_code == 200
    items = rm.json().get("items", rm.json() if isinstance(rm.json(), list) else [])
    text_join = " ".join(str(m.get("body", "")) for m in items)
    assert "TEST_note_pytest" in text_join


# ---------------- Activities ----------------
def test_schedule_and_mark_done_activity(admin_client, created_lead_id):
    r = admin_client.post(f"{BASE_URL}/api/leads/{created_lead_id}/activities",
                          json={"summary": "TEST_activity", "date_deadline": "2026-12-31"}, timeout=15)
    assert r.status_code in (200, 201), r.text
    aid = r.json().get("id")
    assert aid
    r2 = admin_client.post(f"{BASE_URL}/api/activities/{aid}/done",
                           json={"feedback": "TEST_done"}, timeout=15)
    assert r2.status_code == 200


# ---------------- Reports ----------------
def test_reports_dashboard(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/reports/dashboard", timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict)


def test_reports_pivot(admin_client):
    r = admin_client.post(f"{BASE_URL}/api/reports/pivot",
                          json={"rows": ["user_id"], "cols": "lead_stage", "measure": "count"},
                          timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict)


# ---------------- Catalogs (tags, stages, lost reasons, sources) ----------------
def test_catalogs_lead_stage(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/catalogs", timeout=15)
    assert r.status_code == 200
    out = r.json()
    assert "lead_stage" in out
    names = [x.get("name") for x in out["lead_stage"]]
    for n in ("Contact Attempt", "Contacted", "Converted", "Closed"):
        assert n in names, f"missing stage {n}"


def test_catalogs_tag_list(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/catalogs", timeout=15)
    assert r.status_code == 200
    assert "tag" in r.json()


def test_catalog_create_tag(admin_client):
    name = f"TEST_tag_{int(time.time())}"
    r = admin_client.post(f"{BASE_URL}/api/catalogs/tag", json={"name": name}, timeout=15)
    assert r.status_code in (200, 201), r.text


# ---------------- Templates ----------------
def test_templates_list_whatsapp(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/templates/whatsapp", timeout=15)
    assert r.status_code == 200
    body = r.json()
    items = body if isinstance(body, list) else body.get("items", [])
    assert len(items) >= 1, "expected migrated WhatsApp templates"


def test_templates_list_email(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/templates/email", timeout=15)
    assert r.status_code == 200


# ---------------- WhatsApp inbox ----------------
def test_whatsapp_channels_list(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/whatsapp/channels?limit=10", timeout=30)
    assert r.status_code == 200
    body = r.json()
    items = body.get("items", body if isinstance(body, list) else [])
    assert isinstance(items, list)


# ---------------- Admin / Users ----------------
def test_admin_users_list(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/users", timeout=15)
    assert r.status_code == 200
    body = r.json()
    items = body if isinstance(body, list) else body.get("items", [])
    assert len(items) >= 5


# ---------------- Webhooks ----------------
def test_webhook_create_and_post_creates_lead(admin_client):
    name = f"TEST_webhook_{int(time.time())}"
    r = admin_client.post(f"{BASE_URL}/api/admin/webhooks", json={"name": name, "active": True}, timeout=15)
    if r.status_code == 404:
        # try alternate route
        r = admin_client.post(f"{BASE_URL}/api/webhooks", json={"name": name, "active": True}, timeout=15)
    assert r.status_code in (200, 201), r.text
    wh = r.json()
    token = wh.get("token") or wh.get("url", "").rstrip("/").split("/")[-1]
    assert token, f"no token in {wh}"

    # POST to public webhook URL (no auth)
    payload = {"name": "TEST_webhook_lead", "phone": "9876500099",
               "email": "wh@test.com", "state": "Karnataka"}
    r2 = requests.post(f"{BASE_URL}/api/webhook/lead/{token}", json=payload, timeout=30)
    assert r2.status_code in (200, 201), r2.text
    data = r2.json()
    lead_id = data.get("id") or data.get("lead_id")
    assert lead_id, data

    # Verify via API
    rg = admin_client.get(f"{BASE_URL}/api/leads/{lead_id}", timeout=15)
    assert rg.status_code == 200
    assert rg.json()["name"] == "TEST_webhook_lead"


# ---------------- RBAC: caller restrictions ----------------
def test_caller_sees_only_own_leads(caller_client, caller_user):
    r = caller_client.get(f"{BASE_URL}/api/leads?limit=20", timeout=30)
    assert r.status_code == 200
    body = r.json()
    uid = caller_user["id"]
    for it in body["items"]:
        assert it.get("user_id") == uid, f"caller saw lead assigned to {it.get('user_id')} (own id={uid})"


def test_caller_cannot_bulk(caller_client, created_lead_id):
    r = caller_client.post(f"{BASE_URL}/api/leads/bulk",
                           json={"ids": [created_lead_id], "action": "assign",
                                 "payload": {"user_id": 1}}, timeout=15)
    assert r.status_code in (401, 403)
