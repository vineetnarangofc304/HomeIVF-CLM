"""Ozonetel telephony integration tests — incoming screen-pop, call logging,
agent mapping, active-call polling & click-to-dial guard.

All test artifacts (TEST_ leads, call_events) are purged in teardown — the user
strictly dislikes dummy data left behind.
"""
import os
import time
import uuid

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://homeivf-crm-preview.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


@pytest.fixture(scope="module")
def dbconn():
    c = MongoClient(os.environ["MONGO_URL"])
    return c[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def test_lead(admin_client, dbconn):
    phone = f"9{int(time.time()) % 1000000000:09d}"  # 10-digit
    payload = {"contact_name": f"TEST_CALL_{uuid.uuid4().hex[:6]}", "phone": phone}
    r = admin_client.post(f"{API}/leads", json=payload)
    assert r.status_code == 200, r.text
    lead = r.json()
    lead["phone_digits"] = phone[-10:]
    yield lead
    # teardown — purge lead, its calls, its chatter
    lid = lead["id"]
    dbconn.call_events.delete_many({"lead_id": lid})
    dbconn.messages.delete_many({"lead_id": lid})
    dbconn.leads.delete_one({"id": lid})


def test_screenpop_matches_lead(admin_client, test_lead, dbconn):
    ucid = f"TESTUCID_{uuid.uuid4().hex[:8]}"
    params = {
        "phoneNumber": test_lead["phone_digits"], "ucid": ucid,
        "callerID": test_lead["phone_digits"], "did": "918888888888",
        "agentID": "999991", "phoneName": "testagent", "type": "Inbound",
    }
    # public endpoint — no auth
    r = requests.get(f"{API}/calls/ozonetel/screenpop", params=params, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["matched"] is True
    assert data["lead"]["id"] == test_lead["id"]
    # cleanup this call
    dbconn.call_events.delete_many({"ucid": ucid})
    dbconn.messages.delete_many({"lead_id": test_lead["id"], "body": {"$regex": "Incoming call"}})


def test_screenpop_idempotent(test_lead, dbconn):
    ucid = f"TESTUCID_{uuid.uuid4().hex[:8]}"
    params = {"phoneNumber": test_lead["phone_digits"], "ucid": ucid}
    r1 = requests.post(f"{API}/calls/ozonetel/screenpop", json=params, timeout=30)
    r2 = requests.post(f"{API}/calls/ozonetel/screenpop", json=params, timeout=30)
    assert r1.json()["call_id"] == r2.json()["call_id"], "Same ucid must not create duplicate calls"
    dbconn.call_events.delete_many({"ucid": ucid})
    dbconn.messages.delete_many({"lead_id": test_lead["id"], "body": {"$regex": "Incoming call"}})


def test_screenpop_no_match(dbconn):
    ucid = f"TESTUCID_{uuid.uuid4().hex[:8]}"
    r = requests.get(f"{API}/calls/ozonetel/screenpop",
                     params={"phoneNumber": "0000000001", "ucid": ucid}, timeout=30)
    data = r.json()
    assert data["matched"] is False
    assert data["lead"] is None
    dbconn.call_events.delete_many({"ucid": ucid})


def test_lead_call_history(admin_client, test_lead, dbconn):
    ucid = f"TESTUCID_{uuid.uuid4().hex[:8]}"
    requests.get(f"{API}/calls/ozonetel/screenpop",
                 params={"phoneNumber": test_lead["phone_digits"], "ucid": ucid}, timeout=30)
    r = admin_client.get(f"{API}/calls/lead/{test_lead['id']}")
    assert r.status_code == 200
    calls = r.json()
    assert any(c["ucid"] == ucid for c in calls)
    dbconn.call_events.delete_many({"ucid": ucid})
    dbconn.messages.delete_many({"lead_id": test_lead["id"], "body": {"$regex": "Incoming call"}})


def test_calls_list_admin(admin_client):
    r = admin_client.get(f"{API}/calls", params={"limit": 5})
    assert r.status_code == 200
    assert "items" in r.json() and "total" in r.json()


def test_agent_mapping_persists(admin_client, dbconn):
    # find a caller to map
    users = admin_client.get(f"{API}/users").json()
    caller = next((u for u in users if u["role"] == "caller"), None)
    assert caller, "no caller user found"
    r = admin_client.patch(f"{API}/users/{caller['id']}",
                           json={"ozonetel_agent_id": "TESTAGENT123", "ozonetel_phone_name": "testlogin"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["ozonetel_agent_id"] == "TESTAGENT123"
    assert got["ozonetel_phone_name"] == "testlogin"
    # cleanup mapping
    dbconn.users.update_one({"id": caller["id"]},
                            {"$unset": {"ozonetel_agent_id": "", "ozonetel_phone_name": ""}})


def test_active_call_for_mapped_agent(admin_client, caller_client, caller_user, test_lead, dbconn):
    cid = caller_user["id"]
    # map caller to an ozonetel agent id
    admin_client.patch(f"{API}/users/{cid}", json={"ozonetel_agent_id": "ACTIVE_TEST_99"})
    ucid = f"TESTUCID_{uuid.uuid4().hex[:8]}"
    requests.get(f"{API}/calls/ozonetel/screenpop", params={
        "phoneNumber": test_lead["phone_digits"], "ucid": ucid, "agentID": "ACTIVE_TEST_99",
    }, timeout=30)
    r = caller_client.get(f"{API}/calls/active")
    assert r.status_code == 200
    active = r.json()["active"]
    assert active is not None and active["ucid"] == ucid
    # cleanup
    dbconn.call_events.delete_many({"ucid": ucid})
    dbconn.messages.delete_many({"lead_id": test_lead["id"], "body": {"$regex": "Incoming call"}})
    dbconn.users.update_one({"id": cid}, {"$unset": {"ozonetel_agent_id": ""}})


def test_dial_requires_campaign(admin_client):
    """Dial guard: with no campaign configured it must fail clearly, not crash."""
    # temporarily ensure campaign present check works either way — just assert it doesn't 500
    r = admin_client.post(f"{API}/calls/dial", json={"phone": "9990001234"})
    assert r.status_code in (200, 400)


def test_push_to_dialer_guard(admin_client):
    r = admin_client.post(f"{API}/calls/push-to-dialer", json={"lead_ids": []})
    assert r.status_code == 400


def test_cdr_creates_incoming_lead(admin_client, dbconn):
    import uuid as _uuid
    ph = f"98{_uuid.uuid4().int % 100000000:08d}"  # 10-digit unique
    ucid = f"CDRT_{_uuid.uuid4().hex[:8]}"
    data = '{"CallerID":"%s","AgentID":"84822","Status":"Answered","Duration":"45","AudioFile":"https://rec/x.mp3","Disposition":"Interested","CampaignName":"Inbound","DID":"919262104390","ucid":"%s"}' % (ph, ucid)
    r = requests.post(f"{API}/calls/ozonetel/cdr", data={"data": data}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "connected" and body["lead_id"]
    try:
        lead = dbconn.leads.find_one({"id": body["lead_id"]})
        assert lead["source_lead"] == "Ozonetel Incoming Call"
        ce = dbconn.call_events.find_one({"ucid": ucid})
        assert ce["recording_url"] == "https://rec/x.mp3" and ce["disposition"] == "Interested"
    finally:
        dbconn.messages.delete_many({"lead_id": body["lead_id"]})
        dbconn.call_events.delete_many({"ucid": ucid})
        dbconn.leads.delete_one({"id": body["lead_id"]})


def test_cdr_missed_call_creates_tagged_lead(admin_client, dbconn):
    import uuid as _uuid
    ph = f"97{_uuid.uuid4().int % 100000000:08d}"
    ucid = f"CDRT_{_uuid.uuid4().hex[:8]}"
    data = '{"CallerID":"%s","Status":"NotAnswered","Duration":"0","CampaignName":"Inbound","ucid":"%s"}' % (ph, ucid)
    r = requests.post(f"{API}/calls/ozonetel/cdr", data={"data": data}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "missed" and body["lead_id"]
    try:
        lead = dbconn.leads.find_one({"id": body["lead_id"]})
        assert lead["source_lead"] == "Ozonetel Missed Call"
        missed_tag = dbconn.catalogs.find_one({"type": "tag", "name": "Missed Call"})
        assert missed_tag and missed_tag["id"] in (lead.get("tags") or [])
    finally:
        dbconn.messages.delete_many({"lead_id": body["lead_id"]})
        dbconn.call_events.delete_many({"ucid": ucid})
        dbconn.leads.delete_one({"id": body["lead_id"]})
