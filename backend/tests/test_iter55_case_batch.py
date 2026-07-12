"""
Iteration 55 backend tests — Case 1-4 batch:
- P0: login stability (admin + callers) no 500s, list endpoints fast
- Case 4: dashboard total_leads == pipeline bucket total; sum(by_stage) == total
- Case 1: WhatsApp channel visibility by role/owner
- Case 2: follow-up reminders owner-only + [sched-5, sched] window; status sync;
          analytics has no 'not_done' 'card' key; 'Not Done' catalog inactive
- Case 3: disposition-map GET/PUT/seeded shape; catalogs exposes disposition_map;
          alternate_number persistence via PATCH.
Cleanup: any lead we create is archived via POST /api/leads/{id}/lost {}.
Follow-ups we create are deleted.
"""
import os
import time
import uuid
from datetime import datetime, timedelta

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER1 = {"email": "caller1@homeivf.com", "password": "HomeIVF@123"}
CALLER2 = {"email": "caller2@homeivf.com", "password": "HomeIVF@123"}

CHANNEL_ID = 11577
CHANNEL_PHONE_DIGITS = "0182163986"


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="session")
def admin_tok():
    return _login(ADMIN)


@pytest.fixture(scope="session")
def admin_headers(admin_tok):
    return _h(admin_tok)


@pytest.fixture(scope="session")
def caller1_tok():
    return _login(CALLER1)


@pytest.fixture(scope="session")
def caller2_tok():
    return _login(CALLER2)


@pytest.fixture(scope="session")
def caller1_id(caller1_tok):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(caller1_tok), timeout=15)
    assert r.status_code == 200
    return r.json()["id"]


# ---------------- P0 regressions ----------------
class TestP0NoFiveHundreds:
    def test_admin_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=20)
        assert r.status_code == 200, r.text

    def test_caller1_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=CALLER1, timeout=20)
        assert r.status_code == 200, r.text

    def test_caller2_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=CALLER2, timeout=20)
        assert r.status_code == 200, r.text

    def test_leads_default_fast(self, admin_headers):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads", headers=admin_headers, timeout=20)
        dt = time.time() - t0
        assert r.status_code == 200, r.text
        assert dt < 3.0, f"leads default slow: {dt:.2f}s"

    def test_leads_pipeline_fast(self, admin_headers):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads?bucket=pipeline", headers=admin_headers, timeout=20)
        dt = time.time() - t0
        assert r.status_code == 200
        assert dt < 3.0, f"pipeline slow: {dt:.2f}s"

    def test_leads_ozonetel_fast(self, admin_headers):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads?bucket=ozonetel", headers=admin_headers, timeout=20)
        dt = time.time() - t0
        assert r.status_code == 200
        assert dt < 3.0

    def test_leads_search_fast(self, admin_headers):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads?search=raj", headers=admin_headers, timeout=20)
        dt = time.time() - t0
        assert r.status_code == 200
        assert dt < 3.0

    def test_caller_leads_200(self, caller1_tok):
        r = requests.get(f"{BASE_URL}/api/leads", headers=_h(caller1_tok), timeout=20)
        assert r.status_code == 200, r.text


# ---------------- Case 4: dashboard consistency ----------------
class TestCase4DashboardMatchesPipeline:
    def test_dashboard_total_equals_pipeline_total(self, admin_headers):
        d = requests.get(f"{BASE_URL}/api/reports/dashboard", headers=admin_headers, timeout=30)
        assert d.status_code == 200, d.text
        dash = d.json()
        total_leads = dash.get("total_leads")
        assert isinstance(total_leads, int), f"missing total_leads: {dash}"

        p = requests.get(f"{BASE_URL}/api/leads?bucket=pipeline&limit=1",
                         headers=admin_headers, timeout=30)
        assert p.status_code == 200, p.text
        pipeline_total = p.json().get("total")
        assert isinstance(pipeline_total, int)

        assert total_leads == pipeline_total, (
            f"dashboard total_leads={total_leads} != pipeline total={pipeline_total}"
        )

    def test_by_stage_sums_to_total(self, admin_headers):
        d = requests.get(f"{BASE_URL}/api/reports/dashboard", headers=admin_headers, timeout=30)
        assert d.status_code == 200
        dash = d.json()
        by_stage = dash.get("by_stage") or dash.get("stage_counts") or {}
        # Accept dict or list of {stage,count}
        if isinstance(by_stage, list):
            s = sum(int(x.get("count", 0)) for x in by_stage)
        else:
            s = sum(int(v) for v in by_stage.values())
        assert s == dash["total_leads"], (
            f"sum(by_stage)={s} != total_leads={dash['total_leads']} by_stage={by_stage}"
        )


# ---------------- Case 1: WhatsApp visibility ----------------
class TestCase1WhatsAppVisibility:
    def test_admin_sees_all_channels(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/whatsapp/channels?limit=1",
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        assert isinstance(j.get("total"), int)
        assert j["total"] > 1000, f"expected many channels for admin, got {j['total']}"

    def test_caller_unread_summary_200(self, caller1_tok):
        r = requests.get(f"{BASE_URL}/api/whatsapp/unread-summary",
                         headers=_h(caller1_tok), timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "total_unread" in j and "unread_chats" in j

    def test_caller_visibility_owner_filter(self, admin_headers, caller1_tok, caller2_tok,
                                            caller1_id):
        """Create a lead with the channel-matching phone, assign to caller1, ensure
        caller1 sees the channel in search but caller2 does not."""
        digits = CHANNEL_PHONE_DIGITS
        payload = {
            "name": f"TEST_WAOWNER_{uuid.uuid4().hex[:6]}",
            "contact_name": "TEST WAOwner",
            "phone": digits,
        }
        cr = requests.post(f"{BASE_URL}/api/leads", json=payload,
                           headers=admin_headers, timeout=20)
        assert cr.status_code in (200, 201), cr.text
        lead = cr.json()
        lead_id = lead["id"]
        try:
            # Assign to caller1 (id 22 per problem statement, but read live)
            pr = requests.patch(
                f"{BASE_URL}/api/leads/{lead_id}",
                json={"updates": {"user_id": caller1_id}},
                headers=admin_headers, timeout=20,
            )
            assert pr.status_code == 200, pr.text

            # Caller1 should see the channel via search
            r1 = requests.get(
                f"{BASE_URL}/api/whatsapp/channels",
                params={"search": digits}, headers=_h(caller1_tok), timeout=20,
            )
            assert r1.status_code == 200, r1.text
            j1 = r1.json()
            # Total for caller1 should be >=1 (their assigned channel)
            assert j1["total"] >= 1, f"caller1 should see own channel, got {j1}"

            # Caller2 should see 0 for the same search
            r2 = requests.get(
                f"{BASE_URL}/api/whatsapp/channels",
                params={"search": digits}, headers=_h(caller2_tok), timeout=20,
            )
            assert r2.status_code == 200, r2.text
            j2 = r2.json()
            assert j2["total"] == 0, (
                f"caller2 should NOT see caller1's channel, got total={j2['total']}"
            )
        finally:
            requests.post(f"{BASE_URL}/api/leads/{lead_id}/lost", json={},
                          headers=admin_headers, timeout=20)


# ---------------- Case 2: reminders + status ----------------
class TestCase2Reminders:
    def test_reminders_endpoint_200_admin(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/leads/followups/reminders",
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "reminders" in j
        assert isinstance(j["reminders"], list)

    def test_reminder_owner_only_and_window(self, admin_headers, caller1_tok, caller2_tok,
                                             caller1_id):
        """Create a lead assigned to caller1; caller1 creates a follow-up ~2 min in future.
        Only caller1's reminders should include it; caller2's and admin's should not."""
        payload = {"name": f"TEST_REM_{uuid.uuid4().hex[:6]}",
                   "contact_name": "TEST REM", "phone": f"9{uuid.uuid4().int % 10**9:09d}"}
        cr = requests.post(f"{BASE_URL}/api/leads", json=payload,
                           headers=admin_headers, timeout=20)
        assert cr.status_code in (200, 201), cr.text
        lead_id = cr.json()["id"]
        fid = None
        try:
            # assign to caller1
            requests.patch(f"{BASE_URL}/api/leads/{lead_id}",
                           json={"updates": {"user_id": caller1_id}},
                           headers=admin_headers, timeout=20)
            # IST now + 2 min
            ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
            sched = ist_now + timedelta(minutes=2)
            fu_date = sched.strftime("%Y-%m-%d")
            fu_time = sched.strftime("%H:%M")
            body = {"follow_up_date": fu_date, "follow_up_time": fu_time,
                    "note": "TEST reminder window", "status": None}
            fr = requests.post(f"{BASE_URL}/api/leads/{lead_id}/followups", json=body,
                               headers=_h(caller1_tok), timeout=20)
            assert fr.status_code in (200, 201), fr.text
            fid = fr.json()["id"]

            # caller1 sees reminder
            r1 = requests.get(f"{BASE_URL}/api/leads/followups/reminders",
                              headers=_h(caller1_tok), timeout=20)
            assert r1.status_code == 200
            ids1 = [x["follow_up_id"] for x in r1.json()["reminders"]]
            assert fid in ids1, f"caller1 should see own reminder, got {ids1}"

            # caller2 does NOT see it
            r2 = requests.get(f"{BASE_URL}/api/leads/followups/reminders",
                              headers=_h(caller2_tok), timeout=20)
            assert r2.status_code == 200
            ids2 = [x["follow_up_id"] for x in r2.json()["reminders"]]
            assert fid not in ids2, f"caller2 should NOT see caller1's reminder, got {ids2}"

            # admin does NOT see it (owner-only)
            ra = requests.get(f"{BASE_URL}/api/leads/followups/reminders",
                              headers=admin_headers, timeout=20)
            assert ra.status_code == 200
            idsa = [x["follow_up_id"] for x in ra.json()["reminders"]]
            assert fid not in idsa, f"admin should NOT see other's reminder (owner-only), got {idsa}"

            # Now shift the follow-up to 30 min in the past → should NOT appear for caller1
            past = ist_now - timedelta(minutes=30)
            requests.patch(
                f"{BASE_URL}/api/leads/{lead_id}/followups/{fid}",
                json={"follow_up_date": past.strftime("%Y-%m-%d"),
                      "follow_up_time": past.strftime("%H:%M"),
                      "note": "TEST past window"},
                headers=_h(caller1_tok), timeout=20,
            )
            r1p = requests.get(f"{BASE_URL}/api/leads/followups/reminders",
                               headers=_h(caller1_tok), timeout=20)
            ids1p = [x["follow_up_id"] for x in r1p.json()["reminders"]]
            assert fid not in ids1p, "past-scheduled follow-up must NOT appear in reminders"

            # Shift to 30 min in the future → still outside [sched-5, sched] → NOT appear
            fut = ist_now + timedelta(minutes=30)
            requests.patch(
                f"{BASE_URL}/api/leads/{lead_id}/followups/{fid}",
                json={"follow_up_date": fut.strftime("%Y-%m-%d"),
                      "follow_up_time": fut.strftime("%H:%M"),
                      "note": "TEST far future"},
                headers=_h(caller1_tok), timeout=20,
            )
            r1f = requests.get(f"{BASE_URL}/api/leads/followups/reminders",
                               headers=_h(caller1_tok), timeout=20)
            ids1f = [x["follow_up_id"] for x in r1f.json()["reminders"]]
            assert fid not in ids1f, "far-future follow-up must NOT appear (window is [sched-5, sched])"
        finally:
            if fid:
                requests.delete(f"{BASE_URL}/api/leads/{lead_id}/followups/{fid}",
                                headers=admin_headers, timeout=20)
            requests.post(f"{BASE_URL}/api/leads/{lead_id}/lost", json={},
                          headers=admin_headers, timeout=20)

    def test_status_sync_to_lead(self, admin_headers):
        payload = {"name": f"TEST_FUSTATUS_{uuid.uuid4().hex[:6]}",
                   "contact_name": "TEST FU", "phone": f"9{uuid.uuid4().int % 10**9:09d}"}
        cr = requests.post(f"{BASE_URL}/api/leads", json=payload,
                           headers=admin_headers, timeout=20)
        assert cr.status_code in (200, 201)
        lead_id = cr.json()["id"]
        fid = None
        try:
            body = {"follow_up_date": datetime.utcnow().strftime("%Y-%m-%d"),
                    "follow_up_time": "10:00", "note": "TEST status sync", "status": None}
            fr = requests.post(f"{BASE_URL}/api/leads/{lead_id}/followups", json=body,
                               headers=admin_headers, timeout=20)
            assert fr.status_code in (200, 201)
            fid = fr.json()["id"]
            sr = requests.post(
                f"{BASE_URL}/api/leads/{lead_id}/followups/{fid}/status",
                json={"status": "Completed"}, headers=admin_headers, timeout=20,
            )
            assert sr.status_code == 200, sr.text

            gr = requests.get(f"{BASE_URL}/api/leads/{lead_id}",
                              headers=admin_headers, timeout=20)
            assert gr.status_code == 200
            # Lead-level denormalized field must reflect Completed
            assert gr.json().get("follow_up_status") == "Completed", (
                f"lead follow_up_status not synced: {gr.json().get('follow_up_status')}"
            )
        finally:
            if fid:
                requests.delete(f"{BASE_URL}/api/leads/{lead_id}/followups/{fid}",
                                headers=admin_headers, timeout=20)
            requests.post(f"{BASE_URL}/api/leads/{lead_id}/lost", json={},
                          headers=admin_headers, timeout=20)

    def test_not_done_catalog_inactive(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/catalogs", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        cats = r.json()
        fus = cats.get("followup_status") or []
        not_done = [c for c in fus if c.get("name") == "Not Done"]
        # Either absent from active list, or explicitly active:false
        assert all(c.get("active") is False for c in not_done), (
            f"'Not Done' followup_status must be inactive, got {not_done}"
        )


# ---------------- Case 3: disposition map + alternate_number ----------------
class TestCase3DispositionMap:
    def test_get_disposition_map(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/catalogs/disposition-map",
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        m = r.json().get("map", {})
        for k in ("Contact Attempt", "Contacted", "Converted", "Closed"):
            assert k in m, f"expected stage key '{k}' in map, got {list(m.keys())}"
        # Spot-check seeded tags
        assert any("Ringing" in v for v in m.get("Contact Attempt", []))
        assert any("OPD Booked" in v for v in m.get("Contacted", []))

    def test_catalogs_exposes_disposition_map(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/catalogs", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert "disposition_map" in r.json(), "catalogs must expose disposition_map"

    def test_put_disposition_map_persists(self, admin_headers):
        # Read current, add a temp tag, persist, verify, revert
        cur = requests.get(f"{BASE_URL}/api/catalogs/disposition-map",
                           headers=admin_headers, timeout=20).json().get("map", {})
        original = {k: list(v) for k, v in cur.items()}
        temp_tag = f"TEST_TAG_{uuid.uuid4().hex[:6]}"
        edited = {k: list(v) for k, v in cur.items()}
        edited.setdefault("Contact Attempt", []).append(temp_tag)
        pr = requests.put(f"{BASE_URL}/api/catalogs/disposition-map",
                          json={"map": edited}, headers=admin_headers, timeout=20)
        assert pr.status_code == 200, pr.text
        after = requests.get(f"{BASE_URL}/api/catalogs/disposition-map",
                             headers=admin_headers, timeout=20).json().get("map", {})
        assert temp_tag in after.get("Contact Attempt", []), (
            f"temp tag not persisted: {after.get('Contact Attempt')}"
        )
        # Verify tag catalog item auto-created
        cats = requests.get(f"{BASE_URL}/api/catalogs", headers=admin_headers, timeout=20).json()
        tag_names = [c.get("name") for c in (cats.get("tag") or [])]
        assert temp_tag in tag_names, f"temp tag not auto-created in 'tag' catalog: {tag_names[:20]}"
        # Revert
        requests.put(f"{BASE_URL}/api/catalogs/disposition-map",
                     json={"map": original}, headers=admin_headers, timeout=20)

    def test_alternate_number_persists(self, admin_headers):
        payload = {"name": f"TEST_ALT_{uuid.uuid4().hex[:6]}",
                   "contact_name": "TEST ALT", "phone": f"9{uuid.uuid4().int % 10**9:09d}"}
        cr = requests.post(f"{BASE_URL}/api/leads", json=payload,
                           headers=admin_headers, timeout=20)
        assert cr.status_code in (200, 201)
        lead_id = cr.json()["id"]
        try:
            pr = requests.patch(
                f"{BASE_URL}/api/leads/{lead_id}",
                json={"updates": {"alternate_number": "9876500001"}},
                headers=admin_headers, timeout=20,
            )
            assert pr.status_code == 200, pr.text
            gr = requests.get(f"{BASE_URL}/api/leads/{lead_id}",
                              headers=admin_headers, timeout=20)
            assert gr.status_code == 200
            assert gr.json().get("alternate_number") == "9876500001", (
                f"alternate_number not persisted: {gr.json().get('alternate_number')}"
            )
        finally:
            requests.post(f"{BASE_URL}/api/leads/{lead_id}/lost", json={},
                          headers=admin_headers, timeout=20)
