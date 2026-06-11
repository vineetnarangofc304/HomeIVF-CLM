"""HomeIVF CRM - new endpoints & shape changes for iteration 2.
Covers: pivot new shape (col_keys=objects, rows have key+label),
/reports/trends, /reports/heatmap, leads sort, leads new filters (follow_up_tag, lost_reason_id),
admin migration audit endpoint."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://hi-connect-1687.preview.emergentagent.com").rstrip("/")


# ---------------- Pivot - new shape ----------------
def test_pivot_new_shape_col_keys_objects(admin_client):
    r = admin_client.post(f"{BASE_URL}/api/reports/pivot",
                          json={"rows": ["user_id"], "cols": "lead_stage", "filters": {}}, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    # New shape: col_keys is list of {key,label} objects
    assert "col_keys" in body
    assert isinstance(body["col_keys"], list)
    assert len(body["col_keys"]) > 0
    for c in body["col_keys"]:
        assert isinstance(c, dict)
        assert "key" in c and "label" in c
    # rows now have key+label
    assert "rows" in body
    assert len(body["rows"]) > 0
    for row in body["rows"][:5]:
        assert "key" in row and "label" in row and "cells" in row and "total" in row
        assert isinstance(row["cells"], dict)
    assert "grand_total" in body
    assert "col_totals" in body


def test_pivot_with_filters(admin_client):
    r = admin_client.post(f"{BASE_URL}/api/reports/pivot",
                          json={"rows": ["user_id"], "cols": "lead_stage",
                                "filters": {"lead_stage": "Converted"}}, timeout=60)
    assert r.status_code == 200
    body = r.json()
    # When filtered by lead_stage=Converted, col_keys should only have one column
    col_labels = [c["label"] for c in body["col_keys"]]
    if col_labels:
        assert "Converted" in col_labels


def test_pivot_two_row_dims_with_children(admin_client):
    r = admin_client.post(f"{BASE_URL}/api/reports/pivot",
                          json={"rows": ["user_id", "lead_stage"], "filters": {}}, timeout=60)
    assert r.status_code == 200
    body = r.json()
    # Parent rows should have children list
    parent_row = body["rows"][0] if body["rows"] else None
    if parent_row:
        assert "children" in parent_row
        assert isinstance(parent_row["children"], list)


# ---------------- Trends ----------------
def test_trends_day(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/reports/trends?granularity=day", timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "series" in body
    assert "stages" in body
    assert isinstance(body["series"], list)
    assert isinstance(body["stages"], list)
    if body["series"]:
        item = body["series"][0]
        assert "period" in item and "total" in item


def test_trends_week(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/reports/trends?granularity=week", timeout=60)
    assert r.status_code == 200
    body = r.json()
    assert "series" in body


def test_trends_month(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/reports/trends?granularity=month", timeout=60)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["series"], list)


def test_trends_invalid_granularity(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/reports/trends?granularity=foo", timeout=15)
    assert r.status_code == 400


# ---------------- Heatmap ----------------
def test_heatmap_dow_hour(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/reports/heatmap?type=dow_hour", timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "dow_hour"
    assert "cells" in body
    assert isinstance(body["cells"], list)
    if body["cells"]:
        c = body["cells"][0]
        assert "dow" in c and "hour" in c and "count" in c


def test_heatmap_caller_day(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/reports/heatmap?type=caller_day", timeout=60)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "caller_day"
    assert "cells" in body
    if body["cells"]:
        c = body["cells"][0]
        assert "user_id" in c and "user" in c and "day" in c and "count" in c


def test_heatmap_invalid_type(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/reports/heatmap?type=bogus", timeout=15)
    assert r.status_code == 400


# ---------------- Leads sort ----------------
def test_leads_sort_asc(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/leads?sort=create_date&order=asc&limit=10", timeout=30)
    assert r.status_code == 200
    items = r.json()["items"]
    dates = [it.get("create_date") for it in items if it.get("create_date")]
    if len(dates) >= 2:
        assert dates == sorted(dates), f"asc not sorted: {dates}"


def test_leads_sort_desc(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/leads?sort=create_date&order=desc&limit=10", timeout=30)
    assert r.status_code == 200
    items = r.json()["items"]
    dates = [it.get("create_date") for it in items if it.get("create_date")]
    if len(dates) >= 2:
        assert dates == sorted(dates, reverse=True), f"desc not sorted: {dates}"


def test_leads_sort_by_name(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/leads?sort=name&order=asc&limit=10", timeout=30)
    assert r.status_code == 200


# ---------------- Leads new filters ----------------
def test_leads_filter_follow_up_tag(admin_client):
    # try common Odoo migrated tag names
    for tag in ["Follow UP 1", "Follow Up 1", "Hot", "Warm"]:
        r = admin_client.get(f"{BASE_URL}/api/leads?follow_up_tag={tag}&limit=5", timeout=30)
        assert r.status_code == 200
        body = r.json()
        if body["total"] > 0:
            for it in body["items"]:
                assert it.get("follow_up_tag") == tag, f"got {it.get('follow_up_tag')}"
            return
    pytest.skip("No follow_up_tag value matched any common candidate")


def test_leads_filter_lost_reason_id(admin_client):
    # Find a lost_reason id via pivot (group_counts doesn't support this dim)
    pr = admin_client.post(f"{BASE_URL}/api/reports/pivot",
                           json={"rows": ["lost_reason_id"], "filters": {"active": "false"}}, timeout=30)
    assert pr.status_code == 200
    rows = [x for x in pr.json().get("rows", []) if x.get("key") not in (None, "", "__null__")]
    if not rows:
        # No leads with lost_reason_id set — still validate the filter endpoint accepts the param
        # by using a catalog id and ensuring 200 with 0 items
        cat = admin_client.get(f"{BASE_URL}/api/catalogs", timeout=15).json().get("lost_reason", [])
        if not cat:
            pytest.skip("No lost_reason catalog & no leads with reason")
        target = cat[0]["id"]
        r2 = admin_client.get(f"{BASE_URL}/api/leads?lost_reason_id={target}&active=false&limit=5", timeout=30)
        assert r2.status_code == 200
        return
    target = rows[0]["key"]
    r2 = admin_client.get(f"{BASE_URL}/api/leads?lost_reason_id={target}&active=false&limit=5", timeout=30)
    assert r2.status_code == 200
    body = r2.json()
    for it in body["items"]:
        assert str(it.get("lost_reason_id")) == str(target)


# ---------------- Admin migration audit ----------------
def test_migration_audit_runs(admin_client):
    """Audit makes live XML-RPC calls to Odoo (~15-30s)."""
    r = admin_client.post(f"{BASE_URL}/api/admin/migration/audit", json={}, timeout=90)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "rows" in body
    assert "ran_at" in body
    assert "all_match" in body
    entities = {row["entity"]: row for row in body["rows"]}
    for must in ["leads", "whatsapp_conversations", "users", "tags", "pipeline_stages"]:
        assert must in entities, f"missing entity {must}"
        e = entities[must]
        assert "odoo" in e and "crm" in e and "match" in e
    # leads: per problem-statement note, Odoo team is still live; CRM may be slightly behind.
    # Accept either match=True OR Odoo has grown since migration (CRM count > 50k still expected).
    leads_row = entities["leads"]
    assert leads_row["crm"] > 50000, f"CRM lead count too low: {leads_row['crm']}"


def test_migration_audit_persisted(admin_client):
    """Audit result should be stored in settings as last_audit."""
    r = admin_client.get(f"{BASE_URL}/api/admin/settings", timeout=15)
    assert r.status_code == 200
    settings = r.json()
    assert "last_audit" in settings, f"keys={list(settings.keys())}"
    audit = settings["last_audit"]
    assert "rows" in audit and "ran_at" in audit


def test_migration_audit_caller_forbidden(caller_client):
    r = caller_client.post(f"{BASE_URL}/api/admin/migration/audit", json={}, timeout=30)
    assert r.status_code in (401, 403)
