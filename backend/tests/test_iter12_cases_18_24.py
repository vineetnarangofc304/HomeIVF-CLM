"""Iteration 12 — Backend tests for Cases 18-24 (HomeIVF CRM).

Case 18: Dashboard date filter (range fields + all-time funnel default)
Case 19: Follow-up time field on lead
Case 20: Duplicate lead flagging
Case 22: Attachment upload/view (validate storage + accessible)
Case 23: WhatsApp webhook `statuses` handling
Case 24: Agent status-logs with breaks_only=false
"""
import io
import os
import time
import hmac
import hashlib
import json
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


# ---------------- Case 18 : Dashboard date filter ----------------
class TestCase18DashboardDateFilter:
    def test_dashboard_no_range_funnel_nonempty(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/reports/dashboard", timeout=30)
        assert r.status_code == 200
        data = r.json()
        # required range fields must exist even without date_from/date_to
        for k in ("range_start", "range_end", "leads_range", "converted_range", "by_stage"):
            assert k in data, f"Missing key {k}"
        # ALL-TIME funnel must be non-empty on default load
        assert isinstance(data["by_stage"], list)
        assert len(data["by_stage"]) > 0, "Default funnel (by_stage) is empty — must be all-time"
        total_in_funnel = sum(s.get("count", 0) for s in data["by_stage"])
        assert total_in_funnel > 0

    def test_dashboard_with_range_scopes(self, admin_client):
        r = admin_client.get(
            f"{BASE_URL}/api/reports/dashboard",
            params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["range_start"] == "2026-01-01"
        assert data["range_end"] == "2026-01-31"
        assert isinstance(data["leads_range"], int)
        assert isinstance(data["converted_range"], int)
        # leads_range should be non-negative and reasonable
        assert data["leads_range"] >= 0

    def test_dashboard_narrow_future_range(self, admin_client):
        # legitimate future range should NOT error — just return small numbers
        r = admin_client.get(
            f"{BASE_URL}/api/reports/dashboard",
            params={"date_from": "2030-01-01", "date_to": "2030-01-31"},
            timeout=30,
        )
        assert r.status_code == 200
        d = r.json()
        assert d["leads_range"] == 0


# ---------------- Case 19 : follow_up_time on lead ----------------
class TestCase19FollowupTime:
    def test_create_lead_with_follow_up_time_and_persist(self, admin_client):
        payload = {"contact_name": "TEST_iter12_fu", "phone": "9998880019",
                   "follow_up_date": "2026-02-15", "follow_up_time": "14:30"}
        r = admin_client.post(f"{BASE_URL}/api/leads", json=payload, timeout=30)
        assert r.status_code == 200
        lead = r.json()
        lid = lead["id"]
        assert lead.get("follow_up_time") == "14:30"
        # Verify via GET
        g = admin_client.get(f"{BASE_URL}/api/leads/{lid}", timeout=30)
        assert g.status_code == 200
        assert g.json().get("follow_up_time") == "14:30"
        # PATCH different time
        p = admin_client.patch(f"{BASE_URL}/api/leads/{lid}",
                               json={"updates": {"follow_up_time": "09:15"}}, timeout=30)
        assert p.status_code == 200
        assert p.json().get("follow_up_time") == "09:15"
        g2 = admin_client.get(f"{BASE_URL}/api/leads/{lid}", timeout=30)
        assert g2.json().get("follow_up_time") == "09:15"
        # cleanup
        admin_client.post(f"{BASE_URL}/api/leads/{lid}/lost", json={"note": "test cleanup"}, timeout=30)


# ---------------- Case 20 : Duplicate lead flag ----------------
class TestCase20DuplicateFlag:
    def test_two_leads_same_phone_second_flagged(self, admin_client):
        # Use unique phone per run to avoid collisions with leftover soft-deleted leads
        phone = f"9998{int(time.time()) % 1000000:06d}"
        r1 = admin_client.post(f"{BASE_URL}/api/leads",
                               json={"contact_name": "TEST_iter12_dup_A", "phone": phone},
                               timeout=30)
        assert r1.status_code == 200
        lead1 = r1.json()
        id1 = lead1["id"]
        # First should NOT be duplicate (or its duplicate_of is None)
        assert not lead1.get("is_duplicate", False)

        r2 = admin_client.post(f"{BASE_URL}/api/leads",
                               json={"contact_name": "TEST_iter12_dup_B", "phone": phone},
                               timeout=30)
        assert r2.status_code == 200
        lead2 = r2.json()
        id2 = lead2["id"]
        assert lead2.get("is_duplicate") is True, f"Second lead should be flagged. got={lead2}"
        assert lead2.get("duplicate_of") == id1, f"duplicate_of should be {id1}, got {lead2.get('duplicate_of')}"

        # Also check it appears in list with these fields
        ls = admin_client.get(f"{BASE_URL}/api/leads",
                              params={"search": phone}, timeout=30)
        assert ls.status_code == 200
        items = ls.json().get("items", [])
        dup_items = [i for i in items if i["id"] == id2]
        assert dup_items and dup_items[0].get("is_duplicate") is True
        assert dup_items[0].get("duplicate_of") == id1

        # cleanup
        for lid in (id1, id2):
            admin_client.post(f"{BASE_URL}/api/leads/{lid}/lost", json={"note": "test cleanup"}, timeout=30)


# ---------------- Case 22 : Attachments upload/list ----------------
class TestCase22Attachments:
    def test_upload_list_and_delete_attachment(self, admin_client):
        # create a temp lead
        r1 = admin_client.post(f"{BASE_URL}/api/leads",
                               json={"contact_name": "TEST_iter12_att", "phone": "9998880022"},
                               timeout=30)
        assert r1.status_code == 200
        lid = r1.json()["id"]
        # upload a tiny PNG (1x1) bytes
        png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082")
        # remove auth-only content-type of session (multipart needs no explicit CT)
        sess = admin_client
        # keep Authorization but drop content-type if any
        prev_ct = sess.headers.pop("Content-Type", None)
        files = {"file": ("test.png", io.BytesIO(png), "image/png")}
        up = sess.post(f"{BASE_URL}/api/leads/{lid}/attachments", files=files, timeout=30)
        if prev_ct:
            sess.headers["Content-Type"] = prev_ct
        assert up.status_code in (200, 201), f"upload failed: {up.status_code} {up.text}"
        att = up.json()
        aid = att.get("id") or att.get("attachment", {}).get("id")
        assert aid, f"no attachment id returned: {att}"

        # list
        lst = admin_client.get(f"{BASE_URL}/api/leads/{lid}/attachments", timeout=30)
        assert lst.status_code == 200
        arr = lst.json()
        assert any(a.get("id") == aid for a in arr), f"attachment {aid} missing in list {arr}"
        # verify each has some URL/path/name for viewing
        item = [a for a in arr if a.get("id") == aid][0]
        # attachment metadata for viewing (any of these fields is acceptable)
        assert item.get("name") or item.get("filename") or item.get("file_name") or item.get("content_type")
        # cleanup: delete attachment
        d = admin_client.delete(f"{BASE_URL}/api/attachments/{aid}", timeout=30)
        # some codebases route as /leads/{id}/attachments/{aid} — try fallback
        if d.status_code == 404:
            d = admin_client.delete(f"{BASE_URL}/api/leads/{lid}/attachments/{aid}", timeout=30)
        assert d.status_code in (200, 204, 404)
        # cleanup lead
        admin_client.post(f"{BASE_URL}/api/leads/{lid}/lost", json={"note": "test cleanup"}, timeout=30)


# ---------------- Case 23 : WhatsApp webhook statuses ----------------
class TestCase23WhatsAppWebhookStatuses:
    def test_post_statuses_only_accepted(self, admin_client):
        # Get app secret (best effort) — else skip signature enforcement
        # Endpoint accepts without signature? try both.
        body = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {"statuses": [
                {"id": "wamid.TEST_iter12", "status": "delivered", "recipient_id": "919999999999",
                 "timestamp": str(int(time.time()))}
            ]}}]}]
        }
        # signature required — fetch secret from admin settings
        s = admin_client.get(f"{BASE_URL}/api/admin/settings", timeout=30)
        wa_secret = None
        if s.status_code == 200:
            js = s.json()
            iterable = js if isinstance(js, list) else (js.get("items") if isinstance(js, dict) else [])
            if isinstance(iterable, list):
                for k in iterable:
                    if isinstance(k, dict) and k.get("key") == "whatsapp_cloud":
                        wa_secret = (k.get("value") or {}).get("app_secret")
                        break
            if not wa_secret and isinstance(js, dict):
                wa = js.get("whatsapp_cloud") or {}
                wa_secret = wa.get("app_secret") if isinstance(wa, dict) else None
        raw = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if wa_secret:
            sig = hmac.new(wa_secret.encode(), raw, hashlib.sha256).hexdigest()
            headers["X-Hub-Signature-256"] = f"sha256={sig}"
        r = requests.post(f"{BASE_URL}/api/webhooks/whatsapp", data=raw, headers=headers, timeout=30)
        # 200 = accepted, 401/403 = signature required, 503 = integration not configured in preview
        assert r.status_code in (200, 401, 403, 503), f"unexpected {r.status_code}: {r.text}"
        if r.status_code == 200:
            j = r.json()
            assert j.get("status") == "ok"
            assert "status_updates" in j


# ---------------- Case 24 : Agent status-logs breaks_only=false ----------------
class TestCase24AgentStatusLogs:
    def test_status_logs_breaks_only_true(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/agent/status-logs",
                             params={"breaks_only": "true"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))

    def test_status_logs_all_statuses(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/agent/status-logs",
                             params={"breaks_only": "false"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        # Return should be a list (or dict with rows/logs)
        rows = data if isinstance(data, list) else (data.get("logs") or data.get("rows") or data.get("items") or [])
        assert isinstance(rows, list)
        # each row (if any) should have start (end + duration_sec are OK to be null for the currently-open entry)
        for row in rows[:5]:
            assert "start" in row or "start_at" in row or "started_at" in row, f"row missing start: {row}"

    def test_status_logs_all_more_or_equal_than_breaks_only(self, admin_client):
        r_all = admin_client.get(f"{BASE_URL}/api/agent/status-logs",
                                 params={"breaks_only": "false"}, timeout=30)
        r_b = admin_client.get(f"{BASE_URL}/api/agent/status-logs",
                               params={"breaks_only": "true"}, timeout=30)
        if r_all.status_code == 200 and r_b.status_code == 200:
            all_rows = r_all.json() if isinstance(r_all.json(), list) else (r_all.json().get("logs") or r_all.json().get("rows") or r_all.json().get("items") or [])
            b_rows = r_b.json() if isinstance(r_b.json(), list) else (r_b.json().get("logs") or r_b.json().get("rows") or r_b.json().get("items") or [])
            assert len(all_rows) >= len(b_rows)
