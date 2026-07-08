"""Iteration 35 - Backend tests for 6 new cases (Follow-up notes, Caller Activities,
Country default, Reminders, Analytics, Follow-up status dropdown, Export xlsx)."""
import os
import requests
import pytest

def _load_env():
    p = "/app/frontend/.env"
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    return os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


BASE_URL = _load_env()
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER = {"email": "agent@homeivf.com", "password": "Agent@2026"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    assert tok
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_h():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def caller_h():
    return _login(CALLER)


@pytest.fixture(scope="module")
def test_lead(admin_h):
    payload = {"contact_name": "TEST_iter35 Lead", "phone": "9990001111"}
    r = requests.post(f"{API}/leads", json=payload, headers=admin_h, timeout=30)
    assert r.status_code in (200, 201), r.text
    lead = r.json()
    yield lead
    try:
        requests.delete(f"{API}/leads/{lead['id']}", headers=admin_h, timeout=15)
    except Exception:
        pass


# ---------------- Case 1: follow-up note mandatory ----------------
def test_followup_requires_note(admin_h, test_lead):
    r = requests.post(f"{API}/leads/{test_lead['id']}/followups", json={"note": "  "}, headers=admin_h, timeout=15)
    assert r.status_code == 400, r.text
    assert "note" in r.text.lower()


def test_followup_create_with_note_and_status(admin_h, test_lead):
    body = {"note": "TEST call back tomorrow", "follow_up_date": "2030-01-01",
            "follow_up_time": "10:30", "status": "Rescheduled"}
    r = requests.post(f"{API}/leads/{test_lead['id']}/followups", json=body, headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["note"] == "TEST call back tomorrow"
    assert d["status"] == "Rescheduled"
    assert "id" in d
    # Persist verification
    r2 = requests.get(f"{API}/leads/{test_lead['id']}/followups", headers=admin_h, timeout=15)
    assert r2.status_code == 200
    ids = [x["id"] for x in r2.json()]
    assert d["id"] in ids
    pytest.fu_id = d["id"]  # stash for other tests


def test_followup_status_endpoint(admin_h, test_lead):
    fid = pytest.fu_id
    r = requests.post(f"{API}/leads/{test_lead['id']}/followups/{fid}/status",
                      json={"status": "Completed"}, headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "Completed"


def test_followup_patch_requires_note(admin_h, test_lead):
    fid = pytest.fu_id
    r = requests.patch(f"{API}/leads/{test_lead['id']}/followups/{fid}",
                       json={"note": ""}, headers=admin_h, timeout=15)
    assert r.status_code == 400


# ---------------- Case 2: caller activities ----------------
def test_caller_activity_empty_rejected(admin_h, test_lead):
    r = requests.post(f"{API}/leads/{test_lead['id']}/caller-activities",
                      json={"feedback": "   "}, headers=admin_h, timeout=15)
    assert r.status_code == 400


def test_caller_activity_create_and_list(admin_h, test_lead):
    r = requests.post(f"{API}/leads/{test_lead['id']}/caller-activities",
                      json={"feedback": "TEST feedback A"}, headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["feedback"] == "TEST feedback A"
    assert a.get("created_by_name")
    assert a.get("created_at")

    # add a 2nd one
    r2 = requests.post(f"{API}/leads/{test_lead['id']}/caller-activities",
                       json={"feedback": "TEST feedback B"}, headers=admin_h, timeout=15)
    assert r2.status_code == 200

    lst = requests.get(f"{API}/leads/{test_lead['id']}/caller-activities", headers=admin_h, timeout=15).json()
    assert len(lst) >= 2
    # newest-first
    assert lst[0]["feedback"] == "TEST feedback B"


# ---------------- Case 3: country default India ----------------
def test_create_lead_defaults_country_to_india(admin_h):
    r = requests.post(f"{API}/leads", json={"contact_name": "TEST_country_default", "phone": "9990002222"},
                      headers=admin_h, timeout=15)
    assert r.status_code in (200, 201), r.text
    lead = r.json()
    assert lead.get("country") == "India"
    requests.delete(f"{API}/leads/{lead['id']}", headers=admin_h, timeout=15)


def test_create_lead_respects_provided_country(admin_h):
    r = requests.post(f"{API}/leads", json={"contact_name": "TEST_country_us", "phone": "9990003333",
                                             "country": "United States"}, headers=admin_h, timeout=15)
    assert r.status_code in (200, 201)
    lead = r.json()
    assert lead.get("country") == "United States"
    requests.delete(f"{API}/leads/{lead['id']}", headers=admin_h, timeout=15)


# ---------------- Case 5: analytics + Case 4: reminders ----------------
def test_followups_analytics_shape(admin_h):
    r = requests.get(f"{API}/leads/followups/analytics", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("total", "completed", "not_done", "rescheduled", "cancelled", "pending"):
        assert k in d, f"missing key {k}"
        assert isinstance(d[k], int)


def test_followups_analytics_specific_date(admin_h):
    r = requests.get(f"{API}/leads/followups/analytics?date=2030-01-01", headers=admin_h, timeout=15)
    assert r.status_code == 200
    d = r.json()
    # our test follow-up was created on 2030-01-01 with status Completed
    assert d["completed"] >= 1


def test_followups_reminders(admin_h):
    r = requests.get(f"{API}/leads/followups/reminders", headers=admin_h, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "now" in d and "reminders" in d
    assert isinstance(d["reminders"], list)


def test_followups_reminders_caller_scoped(caller_h):
    r = requests.get(f"{API}/leads/followups/reminders", headers=caller_h, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "reminders" in d


# ---------------- Case 7 / Case 6: export xlsx ----------------
def test_export_leads_xlsx_admin(admin_h):
    r = requests.get(f"{API}/export/leads.xlsx?bucket=pipeline", headers=admin_h, timeout=60)
    assert r.status_code == 200, r.text[:400]
    ct = r.headers.get("content-type", "")
    assert "spreadsheet" in ct or "excel" in ct or "octet-stream" in ct, ct
    assert len(r.content) > 200


def test_export_leads_xlsx_caller_forbidden(caller_h):
    r = requests.get(f"{API}/export/leads.xlsx?bucket=pipeline", headers=caller_h, timeout=30)
    assert r.status_code in (401, 403), f"caller should be forbidden, got {r.status_code}"


# ---------------- Catalogs: followup_status seeded ----------------
def test_catalogs_followup_status_seeded(admin_h):
    r = requests.get(f"{API}/catalogs", headers=admin_h, timeout=15)
    assert r.status_code == 200
    cat = r.json()
    assert "followup_status" in cat, list(cat.keys())
    names = {c.get("name") if isinstance(c, dict) else c for c in cat["followup_status"]}
    for expected in ("Completed", "Not Done", "Rescheduled", "Cancelled"):
        assert expected in names, f"missing status {expected}; got {names}"
