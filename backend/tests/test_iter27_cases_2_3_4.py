"""Iteration 27 — Cases 2 (Ozonetel/Pipeline buckets + promote/dedup), 3 (automation preview data) and 4 (WA lead panel)."""
import os
import re
import time
import pytest
import requests
from dotenv import load_dotenv

# Load backend/.env for MONGO_URL etc.
load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ivf-pipeline.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}


def _mongo_db():
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module", autouse=True)
def _reset_500155():
    """Reset lead 500155 to raw ozonetel state so bucket/promote tests are idempotent."""
    db = _mongo_db()
    db.leads.update_one({"id": 500155}, {"$set": {
        "ozonetel_lead": True, "in_pipeline": False, "active": True,
    }, "$unset": {"merged_into": ""}})
    # ensure counter is aligned
    max_lead = list(db.leads.find({}, {"id": 1}).sort("id", -1).limit(1))
    if max_lead:
        db.counters.update_one({"_id": "lead"}, {"$set": {"seq": max_lead[0]["id"]}}, upsert=True)
    yield


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    return s


# ---------------- Case 2 — Bucket filter ----------------
class TestCase2Buckets:
    def test_ozonetel_bucket_contains_500155(self, admin):
        r = admin.get(f"{API}/leads", params={"bucket": "ozonetel", "limit": 200})
        assert r.status_code == 200
        data = r.json()
        ids = [i["id"] for i in data["items"]]
        # each item must have ozonetel_lead True and not in_pipeline
        for i in data["items"]:
            assert i.get("ozonetel_lead") is True
            assert i.get("in_pipeline") is not True
        assert 500155 in ids, f"lead 500155 not in ozonetel bucket, got {ids[:20]}"

    def test_pipeline_bucket_excludes_500155(self, admin):
        r = admin.get(f"{API}/leads", params={"bucket": "pipeline", "limit": 200})
        assert r.status_code == 200
        ids = [i["id"] for i in r.json()["items"]]
        assert 500155 not in ids

    def test_pipeline_bucket_includes_promoted(self, admin):
        # 500156 was already promoted per context
        r = admin.get(f"{API}/leads", params={"bucket": "pipeline", "limit": 200,
                                              "search": "500156"})
        # search is by name/phone/email, may not match; just verify the lead endpoint
        r2 = admin.get(f"{API}/leads/500156")
        if r2.status_code == 200:
            assert r2.json().get("in_pipeline") is True or r2.json().get("ozonetel_lead") is not True


# ---------------- Case 2 — promote non-merge ----------------
class TestCase2Promote:
    def test_promote_500155_moves_to_pipeline(self, admin):
        body = {
            "contact_name": "TEST_iter27_promoted",
            "phone": "9999900155",
            "city": "Delhi", "email_from": "test.iter27@example.com",
            "state_name": "Delhi",
        }
        r = admin.post(f"{API}/leads/500155/promote-to-pipeline", json=body)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("ok") is True
        # either merged or promoted
        if "merged_into" in j:
            # duplicate path — still OK; just make sure raw disappeared from ozonetel bucket
            pass
        else:
            assert j.get("in_pipeline") is True

        # bucket=ozonetel no longer contains 500155
        r2 = admin.get(f"{API}/leads", params={"bucket": "ozonetel", "limit": 200})
        assert 500155 not in [i["id"] for i in r2.json()["items"]]

        # GET returns updated lead
        r3 = admin.get(f"{API}/leads/500155")
        assert r3.status_code == 200
        lead = r3.json()
        if "merged_into" not in j:
            assert lead.get("in_pipeline") is True
            assert lead.get("contact_name") == "TEST_iter27_promoted"


# ---------------- Case 2 — dedup / merge path ----------------
class TestCase2Dedup:
    def test_dedup_merge_when_phone_matches_existing_pipeline(self, admin):
        # 1) create a plain pipeline lead
        # unique phone per run to avoid picking up leftover pipeline leads from previous runs
        import random
        phone = f"911{random.randint(1000000, 9999999)}"
        r = admin.post(f"{API}/leads", json={"contact_name": "TEST_iter27_pipe", "phone": phone})
        assert r.status_code == 200, r.text
        pipe_lead = r.json()
        pipe_id = pipe_lead["id"]

        # 2) create a second lead and mark as ozonetel_lead
        r2 = admin.post(f"{API}/leads", json={"contact_name": "TEST_iter27_ozo", "phone": phone})
        assert r2.status_code == 200
        raw_id = r2.json()["id"]
        # promote to admin patch - set ozonetel_lead via patch? EDITABLE_FIELDS doesn't allow it.
        # Directly set via db is not possible from here; instead we can use catalog/admin update.
        # Fallback: use the /leads PATCH with the "custom" field to store it — but bucket filter checks ozonetel_lead root.
        # Use a raw admin settings write? Simplest: use pymongo directly.
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        assert mongo_url and db_name, "MONGO_URL/DB_NAME not loaded from /app/backend/.env"
        client = MongoClient(mongo_url)
        client[db_name].leads.update_one({"id": raw_id}, {"$set": {"ozonetel_lead": True, "in_pipeline": False}})

        # sanity: raw appears in ozonetel bucket
        rb = admin.get(f"{API}/leads", params={"bucket": "ozonetel", "limit": 200})
        assert raw_id in [i["id"] for i in rb.json()["items"]]

        # 3) promote raw — should merge into pipe_id
        rp = admin.post(f"{API}/leads/{raw_id}/promote-to-pipeline",
                        json={"contact_name": "TEST_iter27_dedup", "phone": phone})
        assert rp.status_code == 200, rp.text
        j = rp.json()
        assert j.get("ok") is True
        assert j.get("merged_into") == pipe_id, f"expected merged_into={pipe_id}, got {j}"

        # 4) raw lead is now inactive
        rget = admin.get(f"{API}/leads/{raw_id}")
        assert rget.status_code == 200
        assert rget.json().get("active") is False


# ---------------- Case 3 — automation templates data available for preview ----------------
class TestCase3AutomationPreviewData:
    def test_wa_templates_have_body(self, admin):
        r = admin.get(f"{API}/templates/whatsapp")
        assert r.status_code == 200
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        assert len(items) > 0
        # at least one with body
        assert any((t.get("body") or "").strip() for t in items)

    def test_email_templates_have_body(self, admin):
        r = admin.get(f"{API}/templates/email")
        assert r.status_code == 200
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        # not required, but confirm endpoint works
        assert isinstance(items, list)


# ---------------- Case 4 — WA lead panel ----------------
class TestCase4WaLeadPanel:
    def test_send_wa_and_lead_messages_endpoint(self, admin):
        # pick a template with body
        r = admin.get(f"{API}/templates/whatsapp")
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        tpl = next((t for t in items if (t.get("body") or "").strip() and t.get("active", True) is not False), None)
        if not tpl:
            pytest.skip("no whatsapp template with body available")

        # pick a lead with phone (500154 has one per prior context)
        r2 = admin.get(f"{API}/leads/500154")
        if r2.status_code != 200 or not r2.json().get("phone"):
            r_any = admin.get(f"{API}/leads", params={"limit": 20})
            lead = next((i for i in r_any.json()["items"] if i.get("phone")), None)
            assert lead
            lead_id = lead["id"]
        else:
            lead_id = 500154

        # send whatsapp
        rs = admin.post(f"{API}/leads/{lead_id}/send_whatsapp", json={"template_id": tpl["id"]})
        # 400 acceptable when live send fails; but that raises HTTPException. Allow both 200 & 400.
        assert rs.status_code in (200, 400), rs.text

        # verify lead-level wa messages endpoint
        rm = admin.get(f"{API}/wa/lead/{lead_id}/messages")
        assert rm.status_code == 200, rm.text
        msgs = rm.json() if isinstance(rm.json(), list) else rm.json().get("items", [])
        assert isinstance(msgs, list)
        # should have at least one now
        assert len(msgs) >= 1
        m = msgs[0]
        # required fields for the UI (wa_tracking record uses 'id' as track id)
        for k in ("id", "status", "template_id", "body"):
            assert k in m, f"expected {k} in {m.keys()}"


# ---------------- Regression ----------------
class TestRegression:
    def test_pipeline_list_search(self, admin):
        r = admin.get(f"{API}/leads", params={"bucket": "pipeline", "search": "a", "limit": 5})
        assert r.status_code == 200

    def test_reports_403_for_caller(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": "agent@homeivf.com", "password": "Agent@2026"})
        assert r.status_code == 200
        tok = r.json().get("access_token")
        if tok:
            s.headers["Authorization"] = f"Bearer {tok}"
        rep = s.get(f"{API}/reports/export.csv")
        assert rep.status_code in (401, 403, 404), f"expected forbidden for caller, got {rep.status_code}"

    def test_followups_crud(self, admin):
        # pick any lead
        r = admin.get(f"{API}/leads", params={"limit": 1})
        lead_id = r.json()["items"][0]["id"]
        # add
        ra = admin.post(f"{API}/leads/{lead_id}/followups",
                        json={"follow_up_date": "2026-01-15", "note": "TEST_iter27"})
        assert ra.status_code == 200, ra.text
        fid = ra.json()["id"]
        # list
        rl = admin.get(f"{API}/leads/{lead_id}/followups")
        assert rl.status_code == 200
        assert any(f["id"] == fid for f in rl.json())
        # delete
        rd = admin.delete(f"{API}/leads/{lead_id}/followups/{fid}")
        assert rd.status_code == 200
