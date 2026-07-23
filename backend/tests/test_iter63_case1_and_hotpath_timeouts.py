"""
Iteration 63:
- Case 1 (edit-open + ownership lock: user_id/original_user_id) regression
- Fail-fast max_time_ms + graceful fallbacks on hot polling endpoints
- Re-verify iter62 caller scoping
"""
import os
import pytest
import requests


def _load_base():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        for line in open("/app/frontend/.env"):
            if line.startswith("REACT_APP_BACKEND_URL="):
                v = line.split("=", 1)[1].strip()
                break
    return v.rstrip("/")


BASE_URL = _load_base()
ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER = {"email": "agent@homeivf.com", "password": "Agent@2026"}
CALLER_USER_ID = 1001


def _login(creds):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    return s


@pytest.fixture(scope="module")
def caller_client():
    return _login(CALLER)


@pytest.fixture(scope="module")
def admin_client():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def a_caller_lead(caller_client):
    r = caller_client.get(f"{BASE_URL}/api/leads?page=1&page_size=1", timeout=60)
    assert r.status_code == 200
    items = r.json().get("items") or []
    assert items, "no caller leads found"
    return items[0]


# -------- AUTH --------
class TestAuth:
    def test_admin_me(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert r.status_code == 200
        assert r.json().get("role") == "admin"

    def test_caller_me(self, caller_client):
        r = caller_client.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("role") == "caller"
        assert d.get("id") == CALLER_USER_ID


# -------- CALLER SCOPING (iter62 regression) --------
class TestCallerScoping:
    def test_caller_only_own_leads(self, caller_client):
        r = caller_client.get(f"{BASE_URL}/api/leads?page=1&page_size=50", timeout=60)
        assert r.status_code == 200
        d = r.json()
        total = d.get("total") or d.get("count") or 0
        assert 4000 < total < 7000, f"expected ~5270 got {total}"
        for it in (d.get("items") or [])[:50]:
            uid = it.get("user_id") or it.get("assigned_to")
            assert uid == CALLER_USER_ID

    def test_caller_user_id_override_ignored(self, caller_client):
        r = caller_client.get(f"{BASE_URL}/api/leads?user_id=20&page=1&page_size=25", timeout=60)
        assert r.status_code == 200
        d = r.json()
        total = d.get("total") or 0
        assert 4000 < total < 7000
        for it in (d.get("items") or [])[:20]:
            assert (it.get("user_id") or it.get("assigned_to")) == CALLER_USER_ID

    def test_admin_unscoped_and_filter(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/leads?page=1&page_size=10", timeout=90)
        assert r.status_code == 200
        assert r.json().get("total", 0) > 100000
        r2 = admin_client.get(f"{BASE_URL}/api/leads?user_id={CALLER_USER_ID}&page=1&page_size=10", timeout=60)
        assert r2.status_code == 200
        t2 = r2.json().get("total", 0)
        assert 4000 < t2 < 7000, f"admin filter by user_id={CALLER_USER_ID} got {t2}"


# -------- CASE 1: Edit open + ownership lock --------
class TestEditAndOwnershipLock:
    def test_caller_can_open_any_lead(self, caller_client, admin_client):
        # pick a lead NOT owned by caller (via admin)
        r = admin_client.get(f"{BASE_URL}/api/leads?user_id=20&page=1&page_size=1", timeout=60)
        assert r.status_code == 200
        items = r.json().get("items") or []
        if not items:
            pytest.skip("no user_id=20 lead to test open-any-lead")
        other_id = items[0].get("id") or items[0].get("_id")
        d = caller_client.get(f"{BASE_URL}/api/leads/{other_id}", timeout=30)
        assert d.status_code == 200, f"caller cannot open others' lead: {d.status_code} {d.text[:200]}"

    def test_caller_patch_own_lead_edits_city(self, caller_client, a_caller_lead):
        lead_id = a_caller_lead.get("id") or a_caller_lead.get("_id")
        original_city = a_caller_lead.get("city")
        try:
            new_city = "TEST_iter63_city"
            r = caller_client.patch(
                f"{BASE_URL}/api/leads/{lead_id}",
                json={"updates": {"city": new_city}},
                timeout=30,
            )
            assert r.status_code == 200, f"patch failed: {r.status_code} {r.text[:300]}"
            # verify persistence
            g = caller_client.get(f"{BASE_URL}/api/leads/{lead_id}", timeout=30)
            assert g.status_code == 200
            assert g.json().get("city") == new_city
        finally:
            # revert
            caller_client.patch(
                f"{BASE_URL}/api/leads/{lead_id}",
                json={"updates": {"city": original_city or ""}},
                timeout=30,
            )

    def test_caller_cannot_reassign_or_change_original_user_id(self, caller_client, a_caller_lead):
        lead_id = a_caller_lead.get("id") or a_caller_lead.get("_id")
        original_city = a_caller_lead.get("city")
        original_uid = a_caller_lead.get("user_id")
        original_ouid = a_caller_lead.get("original_user_id")
        try:
            new_city = "TEST_iter63_lock"
            r = caller_client.patch(
                f"{BASE_URL}/api/leads/{lead_id}",
                json={"updates": {"city": new_city, "user_id": 20, "original_user_id": 20}},
                timeout=30,
            )
            assert r.status_code == 200, f"patch failed: {r.status_code} {r.text[:300]}"
            body = r.json()
            # user_id must remain caller
            assert body.get("user_id") in (original_uid, CALLER_USER_ID), (
                f"caller reassigned lead! user_id={body.get('user_id')} expected {original_uid}"
            )
            if original_ouid is not None:
                assert body.get("original_user_id") == original_ouid, (
                    f"original_user_id mutated: {body.get('original_user_id')} vs {original_ouid}"
                )
            # confirm city did persist
            assert body.get("city") == new_city
        finally:
            caller_client.patch(
                f"{BASE_URL}/api/leads/{lead_id}",
                json={"updates": {"city": original_city or ""}},
                timeout=30,
            )

    def test_admin_can_reassign_but_original_user_id_immutable(self, admin_client, a_caller_lead):
        lead_id = a_caller_lead.get("id") or a_caller_lead.get("_id")
        original_uid = a_caller_lead.get("user_id") or CALLER_USER_ID
        original_ouid = a_caller_lead.get("original_user_id")
        target_uid = 20 if original_uid != 20 else 21
        try:
            r = admin_client.patch(
                f"{BASE_URL}/api/leads/{lead_id}",
                json={"updates": {"user_id": target_uid, "original_user_id": 999}},
                timeout=30,
            )
            assert r.status_code == 200, f"admin patch failed: {r.status_code} {r.text[:300]}"
            body = r.json()
            assert body.get("user_id") == target_uid, f"admin reassign didn't take: {body.get('user_id')}"
            if original_ouid is not None:
                assert body.get("original_user_id") == original_ouid, (
                    f"original_user_id mutated: {body.get('original_user_id')} vs {original_ouid}"
                )
            else:
                assert body.get("original_user_id") != 999
        finally:
            admin_client.patch(
                f"{BASE_URL}/api/leads/{lead_id}",
                json={"updates": {"user_id": original_uid}},
                timeout=30,
            )


# -------- HOT POLLING ENDPOINTS (fail-fast + fallback) --------
class TestHotPolling:
    def test_calls_active(self, caller_client):
        r = caller_client.get(f"{BASE_URL}/api/calls/active", timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        d = r.json()
        assert "active" in d, f"shape wrong: {list(d.keys())}"

    def test_whatsapp_unread_summary(self, caller_client):
        r = caller_client.get(f"{BASE_URL}/api/whatsapp/unread-summary", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("total_unread", "unread_chats", "recent"):
            assert k in d, f"missing {k} in {list(d.keys())}"

    def test_agent_me(self, caller_client):
        r = caller_client.get(f"{BASE_URL}/api/agent/me", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "status" in d and "since" in d, f"shape wrong: {list(d.keys())}"

    def test_followups_reminders(self, caller_client):
        r = caller_client.get(f"{BASE_URL}/api/leads/followups/reminders", timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "now" in d and "reminders" in d, f"shape wrong: {list(d.keys())}"
        assert isinstance(d["reminders"], list)


# -------- group_counts + audit --------
class TestGroupCountsAndAudit:
    def test_group_counts_by_stage_caller(self, caller_client):
        r = caller_client.get(f"{BASE_URL}/api/leads/group_counts?group_by=lead_stage", timeout=60)
        assert r.status_code == 200

    def test_group_counts_by_user_id_caller(self, caller_client):
        r = caller_client.get(f"{BASE_URL}/api/leads/group_counts?group_by=user_id", timeout=60)
        assert r.status_code == 200

    def test_group_counts_admin(self, admin_client):
        for gb in ("lead_stage", "user_id"):
            r = admin_client.get(f"{BASE_URL}/api/leads/group_counts?group_by={gb}", timeout=90)
            assert r.status_code == 200, f"{gb} => {r.status_code}"

    def test_audit_trail_after_edit(self, caller_client, a_caller_lead):
        lead_id = a_caller_lead.get("id") or a_caller_lead.get("_id")
        original_city = a_caller_lead.get("city")
        try:
            caller_client.patch(
                f"{BASE_URL}/api/leads/{lead_id}",
                json={"updates": {"city": "TEST_iter63_audit"}},
                timeout=30,
            )
            r = caller_client.get(f"{BASE_URL}/api/leads/{lead_id}/audit", timeout=30)
            assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
            data = r.json()
            arr = data if isinstance(data, list) else data.get("items") or data.get("audit") or []
            assert isinstance(arr, list)
            # ideally has recent entry
        finally:
            caller_client.patch(
                f"{BASE_URL}/api/leads/{lead_id}",
                json={"updates": {"city": original_city or ""}},
                timeout=30,
            )
