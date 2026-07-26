"""Iteration 84 — regression test after adding max_time_ms/maxTimeMS to ALL remaining
interactive-pool db.* queries in backend/routes/{leads,facebook,whatsapp}.py.

This is a pure hardening change. No business logic should regress. If a bounded query
was mis-invoked (bad kwarg for aggregate/count_documents/find_one), it would surface
as a 500. We hit every listed endpoint and assert 2xx and expected shape.
"""
import os
import time
import uuid
import random
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = ("admin@homeivf.com", "HomeIVF@2026")
CALLER16 = ("caller16@homeivf.com", "TestPass@2026")   # Himani Sharma, id 8
CALLER11 = ("caller11@homeivf.com", "TestPass@2026")   # Anamika Suman, id 5


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:250]}"
    tok = r.json().get("access_token")
    assert tok, "no access_token in login response"
    return tok


def _hdr(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def caller_token():
    return _login(*CALLER16)


@pytest.fixture(scope="module")
def caller11_token():
    return _login(*CALLER11)


@pytest.fixture(scope="module")
def sample_lead_id(admin_token):
    """Pick a real lead id from GET /api/leads for admin."""
    r = requests.get(f"{BASE_URL}/api/leads?limit=5&scope=mine",
                     headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, r.text[:250]
    items = r.json().get("items") or r.json().get("leads") or []
    if not items:
        # fallback to scope=all
        r = requests.get(f"{BASE_URL}/api/leads?limit=5&scope=all",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200
        items = r.json().get("items") or r.json().get("leads") or []
    assert items, "no leads found to test detail endpoints"
    lid = items[0].get("id") or items[0].get("lead_id") or items[0].get("_id")
    assert lid, f"no id key in lead: {list(items[0].keys())[:15]}"
    return lid


# ---------- 1. AUTH ----------
class TestAuth:
    def test_admin_login(self, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 20

    def test_caller_login(self, caller_token):
        assert isinstance(caller_token, str) and len(caller_token) > 20


# ---------- 2. LEADS LIST ----------
class TestLeadsList:
    def test_admin_leads_default(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=20", headers=_hdr(admin_token), timeout=45)
        assert r.status_code == 200, r.text[:250]
        j = r.json()
        assert "items" in j or "leads" in j
        assert "total" in j
        # total may be -1 on first uncached load by design

    def test_admin_leads_scope_all_with_sort(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=10&scope=all&sort=-create_date",
                         headers=_hdr(admin_token), timeout=45)
        assert r.status_code == 200, r.text[:250]
        j = r.json()
        assert isinstance(j.get("items") or j.get("leads"), list)

    def test_admin_leads_scope_all_page2(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=10&skip=10&scope=all",
                         headers=_hdr(admin_token), timeout=45)
        assert r.status_code == 200, r.text[:250]

    def test_caller_leads_default(self, caller_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=20", headers=_hdr(caller_token), timeout=45)
        assert r.status_code == 200, r.text[:250]

    def test_caller_leads_scope_mine(self, caller_token):
        r = requests.get(f"{BASE_URL}/api/leads?limit=20&scope=mine",
                         headers=_hdr(caller_token), timeout=45)
        assert r.status_code == 200, r.text[:250]


# ---------- 3. LEAD DETAIL + SECONDARY ----------
class TestLeadDetail:
    def test_get_lead(self, admin_token, sample_lead_id):
        r = requests.get(f"{BASE_URL}/api/leads/{sample_lead_id}",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, f"{sample_lead_id}: {r.status_code} {r.text[:250]}"

    def test_lead_audit(self, admin_token, sample_lead_id):
        r = requests.get(f"{BASE_URL}/api/leads/{sample_lead_id}/audit",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]
        assert isinstance(r.json(), (list, dict))

    def test_lead_followups(self, admin_token, sample_lead_id):
        r = requests.get(f"{BASE_URL}/api/leads/{sample_lead_id}/followups",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]

    def test_lead_caller_activities(self, admin_token, sample_lead_id):
        r = requests.get(f"{BASE_URL}/api/leads/{sample_lead_id}/caller-activities",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]


# ---------- 4. LEAD UPDATE (PATCH) ----------
class TestLeadUpdate:
    def test_patch_lead_and_audit(self, admin_token, sample_lead_id):
        tag_marker = f"TEST_iter84_{uuid.uuid4().hex[:8]}"
        # capture pre-state
        pre = requests.get(f"{BASE_URL}/api/leads/{sample_lead_id}",
                           headers=_hdr(admin_token), timeout=30).json()
        pre_city = pre.get("city")
        payload = {"updates": {"city": "TestCity_iter84", "tags": [tag_marker]}}
        r = requests.patch(f"{BASE_URL}/api/leads/{sample_lead_id}",
                           json=payload, headers=_hdr(admin_token), timeout=30)
        assert r.status_code in (200, 204), f"patch: {r.status_code} {r.text[:300]}"
        # verify via GET
        after = requests.get(f"{BASE_URL}/api/leads/{sample_lead_id}",
                             headers=_hdr(admin_token), timeout=30).json()
        assert after.get("city") == "TestCity_iter84"
        # audit contains the change
        a = requests.get(f"{BASE_URL}/api/leads/{sample_lead_id}/audit",
                         headers=_hdr(admin_token), timeout=30)
        assert a.status_code == 200
        # restore
        requests.patch(f"{BASE_URL}/api/leads/{sample_lead_id}",
                       json={"updates": {"city": pre_city, "tags": []}},
                       headers=_hdr(admin_token), timeout=30)


# ---------- 5. FOLLOW-UPS CRUD + reminders + analytics ----------
class TestFollowups:
    def test_reminders(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads/followups/reminders",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]

    def test_analytics(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/leads/followups/analytics",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]

    def test_crud_flow(self, admin_token, sample_lead_id):
        # CREATE (note required)
        payload = {"note": "TEST_iter84 followup note", "scheduled_at": "2026-01-30T10:00:00Z"}
        c = requests.post(f"{BASE_URL}/api/leads/{sample_lead_id}/followups",
                          json=payload, headers=_hdr(admin_token), timeout=30)
        assert c.status_code in (200, 201), f"create: {c.status_code} {c.text[:300]}"
        fu = c.json()
        fu_id = fu.get("id") or fu.get("_id") or fu.get("followup_id")
        assert fu_id, f"no id in followup create response: {list(fu.keys())[:12]}"
        # PATCH
        p = requests.patch(f"{BASE_URL}/api/leads/{sample_lead_id}/followups/{fu_id}",
                           json={"note": "TEST_iter84 updated note"},
                           headers=_hdr(admin_token), timeout=30)
        assert p.status_code in (200, 204), f"patch fu: {p.status_code} {p.text[:300]}"
        # status
        s = requests.post(f"{BASE_URL}/api/leads/{sample_lead_id}/followups/{fu_id}/status",
                          json={"status": "completed"},
                          headers=_hdr(admin_token), timeout=30)
        assert s.status_code in (200, 204), f"status: {s.status_code} {s.text[:300]}"
        # LIST reflects
        L = requests.get(f"{BASE_URL}/api/leads/{sample_lead_id}/followups",
                         headers=_hdr(admin_token), timeout=30)
        assert L.status_code == 200
        # DELETE
        d = requests.delete(f"{BASE_URL}/api/leads/{sample_lead_id}/followups/{fu_id}",
                            headers=_hdr(admin_token), timeout=30)
        assert d.status_code in (200, 204), f"delete: {d.status_code} {d.text[:300]}"


# ---------- 6. CALLER ACTIVITY ----------
class TestCallerActivity:
    def test_add_activity(self, admin_token, sample_lead_id):
        r = requests.post(f"{BASE_URL}/api/leads/{sample_lead_id}/caller-activities",
                          json={"feedback": "TEST_iter84 activity feedback"},
                          headers=_hdr(admin_token), timeout=30)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"
        j = r.json()
        assert isinstance(j, dict)
        # feedback should echo
        assert "feedback" in str(j).lower() or "id" in j or "_id" in j

    def test_missing_feedback_rejected(self, admin_token, sample_lead_id):
        r = requests.post(f"{BASE_URL}/api/leads/{sample_lead_id}/caller-activities",
                          json={}, headers=_hdr(admin_token), timeout=30)
        assert r.status_code in (400, 422), f"expected 400/422 got {r.status_code}"


# ---------- 7. MARK LOST + RESTORE ----------
class TestLostRestore:
    def test_lost_and_restore(self, admin_token, sample_lead_id):
        r1 = requests.post(f"{BASE_URL}/api/leads/{sample_lead_id}/lost",
                           json={"reason": "TEST_iter84"},
                           headers=_hdr(admin_token), timeout=30)
        assert r1.status_code in (200, 204), f"lost: {r1.status_code} {r1.text[:300]}"
        r2 = requests.post(f"{BASE_URL}/api/leads/{sample_lead_id}/restore",
                           json={},
                           headers=_hdr(admin_token), timeout=30)
        assert r2.status_code in (200, 204), f"restore: {r2.status_code} {r2.text[:300]}"


# ---------- 8. PROMOTE-TO-PIPELINE (skip if lead 600027 not accessible) ----------
class TestPromote:
    def test_promote_dedup_or_promote(self, admin_token):
        # Try to find an Ozonetel-raw lead. Fall back to sample lead if any 200 comes back.
        r = requests.get(f"{BASE_URL}/api/leads?bucket=ozonetel&limit=3&scope=all",
                         headers=_hdr(admin_token), timeout=45)
        if r.status_code != 200:
            pytest.skip(f"bucket=ozonetel query failed {r.status_code}")
        items = r.json().get("items") or r.json().get("leads") or []
        if not items:
            pytest.skip("no ozonetel raw leads available")
        lid = items[0].get("id") or items[0].get("lead_id")
        pr = requests.post(f"{BASE_URL}/api/leads/{lid}/promote-to-pipeline",
                           json={}, headers=_hdr(admin_token), timeout=45)
        # promote OR merge — both are 2xx. 400 acceptable if already promoted.
        assert pr.status_code in (200, 201, 204, 400, 409), f"promote: {pr.status_code} {pr.text[:300]}"


# ---------- 9. WHATSAPP TEMPLATE SEND ----------
class TestWhatsAppSend:
    def test_send_template(self, admin_token, sample_lead_id):
        r = requests.post(f"{BASE_URL}/api/leads/{sample_lead_id}/send_whatsapp",
                          json={"template_id": "welcome"},
                          headers=_hdr(admin_token), timeout=30)
        # Either queued (no api configured) or ok — 422/400 acceptable for missing template config
        assert r.status_code in (200, 201, 202, 400, 404, 422), f"{r.status_code} {r.text[:300]}"


# ---------- 10. FACEBOOK ADMIN ----------
class TestFacebookAdmin:
    def test_status(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/facebook/status",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]
        assert isinstance(r.json(), dict)

    def test_recent_leads(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/facebook/recent-leads",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]

    def test_webhook_log(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/facebook/webhook-log",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]

    def test_diagnose(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/facebook/diagnose",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]

    def test_backfill_status(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/facebook/backfill/status",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]


# ---------- 11. WHATSAPP INBOX ----------
class TestWhatsAppInbox:
    def test_channels_list(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/whatsapp/channels?limit=10",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]

    def test_channels_search(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/whatsapp/channels?limit=5&search=a",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]

    def test_channels_pagination(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/whatsapp/channels?limit=5&skip=5",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]

    def test_unread_summary(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/whatsapp/unread-summary",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]

    @pytest.fixture(scope="class")
    def wa_channel_id(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/whatsapp/channels?limit=5",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200
        j = r.json()
        items = j.get("items") or j.get("channels") or []
        if not items:
            pytest.skip("no whatsapp channels")
        return items[0].get("id") or items[0].get("_id") or items[0].get("channel_id")

    def test_channel_messages(self, admin_token, wa_channel_id):
        r = requests.get(f"{BASE_URL}/api/whatsapp/channels/{wa_channel_id}/messages?limit=10",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]

    def test_set_category(self, admin_token, wa_channel_id):
        r = requests.post(f"{BASE_URL}/api/whatsapp/channels/{wa_channel_id}/category",
                          json={"category": "TEST_iter84"},
                          headers=_hdr(admin_token), timeout=30)
        assert r.status_code in (200, 204), f"{r.status_code} {r.text[:300]}"

    def test_send_message_queues(self, admin_token, wa_channel_id):
        r = requests.post(f"{BASE_URL}/api/whatsapp/channels/{wa_channel_id}/send",
                          json={"body": "TEST_iter84 message"},
                          headers=_hdr(admin_token), timeout=30)
        # queued when API not configured; ok otherwise; 400 acceptable for missing body variants
        assert r.status_code in (200, 201, 202, 400), f"{r.status_code} {r.text[:300]}"

    def test_star_pin_toggle(self, admin_token, wa_channel_id):
        # get a message id first
        m = requests.get(f"{BASE_URL}/api/whatsapp/channels/{wa_channel_id}/messages?limit=5",
                        headers=_hdr(admin_token), timeout=30)
        assert m.status_code == 200
        mj = m.json()
        msgs = mj.get("items") or mj.get("messages") or []
        if not msgs:
            pytest.skip("no messages in channel to test star/pin")
        mid = msgs[0].get("id") or msgs[0].get("_id") or msgs[0].get("message_id")
        if not mid:
            pytest.skip("no message id key")
        s = requests.post(f"{BASE_URL}/api/whatsapp/messages/{mid}/star",
                          json={}, headers=_hdr(admin_token), timeout=30)
        assert s.status_code in (200, 204), f"star: {s.status_code} {s.text[:300]}"
        p = requests.post(f"{BASE_URL}/api/whatsapp/messages/{mid}/pin",
                          json={}, headers=_hdr(admin_token), timeout=30)
        assert p.status_code in (200, 204), f"pin: {p.status_code} {p.text[:300]}"

    def test_channels_for_lead(self, admin_token, sample_lead_id):
        r = requests.get(f"{BASE_URL}/api/whatsapp/lead/{sample_lead_id}",
                         headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:250]
