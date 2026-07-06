"""Tests for the 'changes & issues' doc batch:
  - Case 2: richer custom field types + drag-drop reorder (sequence)
  - Case 1/3: multi-action automations
  - Case 4: Facebook Lead Ads (verify handshake, signature reject, test-lead mapping, status)

All artifacts purged in teardown (user strictly dislikes dummy data).
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://lead-capture-debug-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


@pytest.fixture(scope="module")
def dbconn():
    c = MongoClient(os.environ["MONGO_URL"])
    return c[os.environ["DB_NAME"]]


# ---------- Case 2: custom field types + reorder ----------
def test_custom_field_new_types_and_reorder(admin_client, dbconn):
    sfx = uuid.uuid4().hex[:6]
    ids = []
    try:
        for ft in ["boolean", "date", "integer", "monetary"]:
            r = admin_client.post(f"{API}/catalogs/custom-fields/create",
                                  json={"label": f"ZZT_{ft}_{sfx}", "field_type": ft, "section": "general"})
            assert r.status_code == 200, r.text
            ids.append(r.json()["id"])
        # invalid type rejected
        bad = admin_client.post(f"{API}/catalogs/custom-fields/create",
                                json={"label": f"ZZT_bad_{sfx}", "field_type": "rocket", "section": "general"})
        assert bad.status_code == 400
        # reorder (reverse) and verify sequence persisted
        rev = list(reversed(ids))
        r = admin_client.post(f"{API}/catalogs/custom-fields/reorder", json={"order": rev})
        assert r.status_code == 200
        allf = {f["id"]: f for f in admin_client.get(f"{API}/catalogs/custom-fields/all").json()}
        seqs = [allf[i]["sequence"] for i in rev]
        assert seqs == sorted(seqs), "sequence should follow the reorder request"
    finally:
        dbconn.custom_fields.delete_many({"label": {"$regex": f"^ZZT_.*{sfx}$"}})


# ---------- Case 1/3: multi-action automation ----------
def test_multi_action_automation(admin_client, dbconn):
    name = f"ZZT_AUTO_{uuid.uuid4().hex[:6]}"
    try:
        r = admin_client.post(f"{API}/admin/automations", json={
            "name": name, "trigger": "on_create", "condition": {},
            "actions": [{"type": "add_tag", "value": 33}, {"type": "set_lead_stage", "value": "Contacted"}],
        })
        assert r.status_code == 200, r.text
        assert len(r.json()["actions"]) == 2
    finally:
        dbconn.automations.delete_many({"name": name})


# ---------- Case 4: Facebook Lead Ads ----------
def test_fb_verify_handshake(admin_client, dbconn):
    token = f"vtok_{uuid.uuid4().hex[:8]}"
    admin_client.patch(f"{API}/admin/settings", json={"key": "facebook", "value": {"verify_token": token}})
    try:
        ok = requests.get(f"{API}/webhooks/facebook",
                          params={"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "ECHO123"}, timeout=30)
        assert ok.status_code == 200 and ok.text == "ECHO123"
        bad = requests.get(f"{API}/webhooks/facebook",
                           params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "x"}, timeout=30)
        assert bad.status_code == 403
    finally:
        dbconn.settings.delete_one({"key": "facebook"})


def test_fb_webhook_rejects_bad_signature(dbconn):
    # configure minimal creds so signature path is exercised
    dbconn.settings.update_one({"key": "facebook"},
                               {"$set": {"key": "facebook", "app_secret": "secret123", "page_access_token": "tok"}}, upsert=True)
    try:
        r = requests.post(f"{API}/webhooks/facebook", json={"entry": []},
                          headers={"X-Hub-Signature-256": "sha256=deadbeef"}, timeout=30)
        assert r.status_code == 401
    finally:
        dbconn.settings.delete_one({"key": "facebook"})


def test_fb_test_lead_mapping(admin_client, dbconn):
    r = admin_client.post(f"{API}/admin/facebook/test", json={
        "field_data": [
            {"name": "full_name", "values": ["ZZT FB Lead"]},
            {"name": "phone_number", "values": ["+919800011122"]},
            {"name": "email", "values": ["zzt_fb@example.com"]},
            {"name": "which_service", "values": ["IVF"]},  # unmapped → custom
        ],
        "leadgen_id": "ZZT_LG_1",
    })
    assert r.status_code == 200, r.text
    lead = r.json()["lead"]
    lid = r.json()["lead_id"]
    try:
        assert lead["contact_name"] == "ZZT FB Lead"
        assert lead["phone"] == "+919800011122"
        assert lead["email_from"] == "zzt_fb@example.com"
        assert lead["custom"].get("x_custom_which_service") == "IVF"
        assert lead.get("facebook_lead") is True
    finally:
        dbconn.messages.delete_many({"lead_id": lid})
        dbconn.leads.delete_one({"id": lid})


def test_fb_status(admin_client):
    r = admin_client.get(f"{API}/admin/facebook/status")
    assert r.status_code == 200
    assert "configured" in r.json() and "leads_captured" in r.json()


# ---------- WhatsApp Cloud API ----------
def test_wa_verify_handshake(admin_client, dbconn):
    token = f"wa_{uuid.uuid4().hex[:8]}"
    admin_client.patch(f"{API}/admin/settings", json={"key": "whatsapp_cloud", "value": {"verify_token": token, "app_secret": "s", "graph_api_version": "v25.0"}})
    try:
        ok = requests.get(f"{API}/webhooks/whatsapp",
                          params={"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "WAECHO"}, timeout=30)
        assert ok.status_code == 200 and ok.text == "WAECHO"
        bad = requests.get(f"{API}/webhooks/whatsapp",
                           params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "y"}, timeout=30)
        assert bad.status_code == 403
    finally:
        dbconn.settings.delete_one({"key": "whatsapp_cloud"})


def test_wa_webhook_rejects_bad_signature(dbconn):
    dbconn.settings.update_one({"key": "whatsapp_cloud"},
                               {"$set": {"key": "whatsapp_cloud", "app_secret": "sek", "verify_token": "v"}}, upsert=True)
    try:
        r = requests.post(f"{API}/webhooks/whatsapp", json={"entry": []},
                          headers={"X-Hub-Signature-256": "sha256=bad"}, timeout=30)
        assert r.status_code == 401
    finally:
        dbconn.settings.delete_one({"key": "whatsapp_cloud"})


def test_wa_status_and_send_guard(admin_client, dbconn):
    # configured=false when phone_number_id missing → send-test must fail gracefully, not crash
    dbconn.settings.update_one({"key": "whatsapp_cloud"},
                               {"$set": {"key": "whatsapp_cloud", "access_token": "tok", "phone_number_id": "", "graph_api_version": "v25.0"}}, upsert=True)
    try:
        s = admin_client.get(f"{API}/admin/whatsapp/status")
        assert s.status_code == 200 and s.json()["configured"] is False
        t = admin_client.post(f"{API}/admin/whatsapp/send-test", json={"to": "919812345678"})
        assert t.status_code == 400
    finally:
        dbconn.settings.delete_one({"key": "whatsapp_cloud"})
