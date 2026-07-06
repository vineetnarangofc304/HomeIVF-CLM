"""Iteration 24 — RBAC matrix + Follow-up entries CRUD.

Covers:
- GET/PATCH /api/admin/role-permissions (admin locked, manager/caller editable)
- Login/me include 'permissions'
- Permission-gated endpoints return 403 for caller/manager as configured
- Follow-up CRUD on /api/leads/{id}/followups syncs lead.follow_up_date
"""
import os
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/") + "/api"

ADMIN = ("admin@homeivf.com", "HomeIVF@2026")
CALLER = ("agent@homeivf.com", "Agent@2026")
MANAGER = ("vikas.chauhan@homeivf.com", "HomeIVF@123")


def _login(email, pwd):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pwd}, timeout=30)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def admin_tok():
    return _login(*ADMIN)["access_token"]


@pytest.fixture(scope="module")
def caller_tok():
    return _login(*CALLER)["access_token"]


@pytest.fixture(scope="module")
def manager_tok():
    return _login(*MANAGER)["access_token"]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- Login/me include permissions ----------
class TestAuthPermissions:
    def test_login_returns_permissions(self):
        data = _login(*CALLER)
        assert "permissions" in data, "login response missing 'permissions'"
        perms = data["permissions"]
        assert perms.get("leads") is True
        assert perms.get("reports") is False
        assert perms.get("marketing") is False
        assert perms.get("admin") is False

    def test_me_returns_permissions(self, admin_tok):
        r = requests.get(f"{BASE}/auth/me", headers=H(admin_tok), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "permissions" in body
        # admin must be all True
        assert all(v is True for v in body["permissions"].values())


# ---------- Role-permissions matrix ----------
class TestRoleMatrix:
    def test_get_matrix_admin(self, admin_tok):
        r = requests.get(f"{BASE}/admin/role-permissions", headers=H(admin_tok), timeout=15)
        assert r.status_code == 200
        body = r.json()
        for key in ("matrix", "all_perms", "module_perms", "action_perms", "labels"):
            assert key in body
        m = body["matrix"]
        assert set(m.keys()) >= {"admin", "manager", "caller"}
        # admin row all true
        assert all(v is True for v in m["admin"].values())
        # caller defaults
        assert m["caller"]["reports"] is False
        assert m["caller"]["export"] is False

    def test_patch_matrix_persists_and_admin_locked(self, admin_tok):
        # Try to reduce admin AND edit caller
        payload = {"matrix": {
            "admin": {"reports": False},  # should be ignored
            "caller": {"reports": True},  # should persist
        }}
        r = requests.patch(f"{BASE}/admin/role-permissions", json=payload,
                           headers=H(admin_tok), timeout=15)
        assert r.status_code == 200
        m = r.json()["matrix"]
        assert m["admin"]["reports"] is True, "Admin must remain full-access"
        assert m["caller"]["reports"] is True, "Caller override should persist"

        # revert
        requests.patch(f"{BASE}/admin/role-permissions",
                       json={"matrix": {"caller": {"reports": False}}},
                       headers=H(admin_tok), timeout=15)

    def test_caller_cannot_patch_matrix(self, caller_tok):
        r = requests.patch(f"{BASE}/admin/role-permissions",
                           json={"matrix": {"caller": {"reports": True}}},
                           headers=H(caller_tok), timeout=15)
        assert r.status_code == 403


# ---------- Permission enforcement ----------
class TestCallerForbidden:
    """Caller should be blocked from reports/marketing/export."""

    def test_reports_pivot(self, caller_tok):
        r = requests.post(f"{BASE}/reports/pivot",
                          json={"rows": ["stage"], "measure": "count"},
                          headers=H(caller_tok), timeout=15)
        assert r.status_code == 403, f"expected 403, got {r.status_code}"

    def test_reports_trends(self, caller_tok):
        r = requests.get(f"{BASE}/reports/trends", headers=H(caller_tok), timeout=15)
        assert r.status_code == 403

    def test_reports_heatmap(self, caller_tok):
        r = requests.get(f"{BASE}/reports/heatmap", headers=H(caller_tok), timeout=15)
        assert r.status_code == 403

    def test_export_leads_xlsx(self, caller_tok):
        r = requests.get(f"{BASE}/export/leads.xlsx", headers=H(caller_tok), timeout=15)
        assert r.status_code == 403

    def test_export_report_pdf(self, caller_tok):
        r = requests.get(f"{BASE}/export/report.pdf", headers=H(caller_tok), timeout=15)
        assert r.status_code == 403

    def test_marketing_campaigns(self, caller_tok):
        r = requests.get(f"{BASE}/marketing/campaigns", headers=H(caller_tok), timeout=15)
        assert r.status_code == 403


class TestManagerPermissions:
    """Manager has reports+marketing but NOT export/manage_users."""

    def test_reports_trends_allowed(self, manager_tok):
        r = requests.get(f"{BASE}/reports/trends", headers=H(manager_tok), timeout=20)
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"

    def test_marketing_campaigns_allowed(self, manager_tok):
        r = requests.get(f"{BASE}/marketing/campaigns", headers=H(manager_tok), timeout=15)
        assert r.status_code == 200

    def test_export_denied(self, manager_tok):
        r = requests.get(f"{BASE}/export/leads.xlsx", headers=H(manager_tok), timeout=15)
        assert r.status_code == 403

    def test_create_user_denied(self, manager_tok):
        r = requests.post(f"{BASE}/users",
                          json={"email": "TEST_shouldfail@x.com", "name": "x",
                                "role": "caller", "password": "Test@2026"},
                          headers=H(manager_tok), timeout=15)
        assert r.status_code == 403


class TestAdminAllowed:
    def test_admin_all_ok(self, admin_tok):
        endpoints = [
            ("GET", "/reports/trends", None),
            ("GET", "/reports/heatmap", None),
            ("GET", "/marketing/campaigns", None),
            ("GET", "/export/leads.xlsx", None),
        ]
        for method, path, body in endpoints:
            r = requests.request(method, f"{BASE}{path}", headers=H(admin_tok),
                                 json=body, timeout=30)
            assert r.status_code == 200, f"admin got {r.status_code} on {path}: {r.text[:200]}"


# ---------- Follow-up CRUD ----------
class TestFollowupsCRUD:
    @pytest.fixture(scope="class")
    def lead_id(self, admin_tok):
        r = requests.get(f"{BASE}/leads?limit=1", headers=H(admin_tok), timeout=15)
        assert r.status_code == 200
        items = r.json().get("items") or []
        assert items, "No leads available"
        return items[0]["id"]

    def test_full_crud(self, admin_tok, lead_id):
        h = H(admin_tok)
        # CREATE
        payload = {"follow_up_date": "2026-06-15", "follow_up_time": "10:30",
                   "follow_up_tag": "call_back", "note": "TEST_iter24 initial"}
        r = requests.post(f"{BASE}/leads/{lead_id}/followups", json=payload, headers=h, timeout=15)
        assert r.status_code == 200, r.text
        fu = r.json()
        fid = fu["id"]
        assert fu["follow_up_date"] == "2026-06-15"
        assert fu["note"] == "TEST_iter24 initial"

        # Lead follow_up_date synced
        lead = requests.get(f"{BASE}/leads/{lead_id}", headers=h, timeout=15).json()
        assert lead.get("follow_up_date") == "2026-06-15"

        # LIST
        r = requests.get(f"{BASE}/leads/{lead_id}/followups", headers=h, timeout=15)
        assert r.status_code == 200
        assert any(x["id"] == fid for x in r.json())

        # PATCH
        r = requests.patch(f"{BASE}/leads/{lead_id}/followups/{fid}",
                           json={"follow_up_date": "2026-07-20", "note": "TEST_iter24 updated",
                                 "follow_up_time": "11:00", "follow_up_tag": "call_back"},
                           headers=h, timeout=15)
        assert r.status_code == 200
        assert r.json()["follow_up_date"] == "2026-07-20"
        assert r.json()["note"] == "TEST_iter24 updated"

        # Lead sync after update
        lead = requests.get(f"{BASE}/leads/{lead_id}", headers=h, timeout=15).json()
        assert lead.get("follow_up_date") == "2026-07-20"

        # DELETE
        r = requests.delete(f"{BASE}/leads/{lead_id}/followups/{fid}", headers=h, timeout=15)
        assert r.status_code == 200
        # gone from list
        r = requests.get(f"{BASE}/leads/{lead_id}/followups", headers=h, timeout=15)
        assert not any(x["id"] == fid for x in r.json())

    def test_missing_date_and_note_returns_400(self, admin_tok, lead_id):
        r = requests.post(f"{BASE}/leads/{lead_id}/followups", json={}, headers=H(admin_tok), timeout=15)
        assert r.status_code == 400
