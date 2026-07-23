#!/usr/bin/env python3
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

import requests


def get_base_url():
    for line in Path('/app/frontend/.env').read_text().splitlines():
        if line.startswith('REACT_APP_BACKEND_URL='):
            return line.split('=', 1)[1].strip().rstrip('/')
    raise RuntimeError('REACT_APP_BACKEND_URL not found')


BASE = get_base_url()
API = BASE + '/api'
LEAD_ID = 600027
SEARCH_PHONE = '5770614172'

CREDS = {
    'admin': ('admin@homeivf.com', 'HomeIVF@2026'),
    'himani': ('caller16@homeivf.com', 'TestPass@2026'),
    'anamika': ('caller11@homeivf.com', 'TestPass@2026'),
}

results = {'base_url': BASE, 'checks': []}


def jdump(x):
    return json.dumps(x, default=str, ensure_ascii=False)


def record(name, ok, details):
    row = {'name': name, 'ok': bool(ok), 'details': details}
    results['checks'].append(row)
    print(('PASS' if ok else 'FAIL') + ' - ' + name + ': ' + jdump(details))


def parse_json(resp):
    try:
        return resp.json()
    except Exception:
        return {'_raw': resp.text[:500]}


def login(label):
    s = requests.Session()
    email, password = CREDS[label]
    r = s.post(API + '/auth/login', json={'email': email, 'password': password}, timeout=30)
    data = parse_json(r)
    if r.status_code == 200 and data.get('access_token'):
        s.headers.update({'Authorization': f"Bearer {data['access_token']}"})
    record(f'login_{label}', r.status_code == 200, {'status': r.status_code, 'email': email, 'user': {k: data.get(k) for k in ('id', 'name', 'role')}})
    return s, data, r.status_code


admin, admin_user, admin_status = login('admin')
himani, himani_user, himani_status = login('himani')
anamika, anamika_user, anamika_status = login('anamika')

if admin_status != 200 or himani_status != 200:
    Path('/app/test_reports/iteration_66_api_results.json').write_text(json.dumps(results, indent=2, default=str))
    raise SystemExit(2)

# Default bucket counts with no search: caller default must be unscoped and match admin.
r = admin.get(API + '/leads', params={'bucket': 'pipeline', 'page': 1, 'limit': 50}, timeout=60)
admin_pipeline = parse_json(r)
record('admin_default_pipeline_reference_count', r.status_code == 200 and admin_pipeline.get('total', 0) > 100000, {
    'status': r.status_code, 'total': admin_pipeline.get('total'), 'items': len(admin_pipeline.get('items', []))
})

r = himani.get(API + '/leads', params={'bucket': 'pipeline', 'page': 1, 'limit': 50}, timeout=60)
caller_pipeline = parse_json(r)
caller_page_user_ids = sorted({it.get('user_id') for it in caller_pipeline.get('items', []) if it.get('user_id') is not None})
record('himani_default_pipeline_all_leads_unscoped', r.status_code == 200 and caller_pipeline.get('total') == admin_pipeline.get('total') and len(caller_page_user_ids) > 1, {
    'status': r.status_code, 'caller_total': caller_pipeline.get('total'), 'admin_total': admin_pipeline.get('total'),
    'distinct_user_ids_first_page': caller_page_user_ids[:25]
})

r = himani.get(API + '/leads', params={'bucket': 'pipeline', 'page': 1, 'limit': 50, 'user_id': himani_user.get('id', 8)}, timeout=60)
my_leads = parse_json(r)
my_page_user_ids = sorted({it.get('user_id') for it in my_leads.get('items', []) if it.get('user_id') is not None})
record('himani_my_leads_filter_narrows_to_own', r.status_code == 200 and 0 < my_leads.get('total', 0) < caller_pipeline.get('total', 0) and set(my_page_user_ids).issubset({himani_user.get('id', 8)}), {
    'status': r.status_code, 'total': my_leads.get('total'), 'distinct_user_ids_first_page': my_page_user_ids
})

r = himani.get(API + '/leads', params={'bucket': 'ozonetel', 'page': 1, 'limit': 50}, timeout=60)
oz_default = parse_json(r)
record('default_ozonetel_bucket_count_unchanged_no_search', r.status_code == 200 and 150 <= oz_default.get('total', 0) <= 300, {
    'status': r.status_code, 'total': oz_default.get('total'), 'items': len(oz_default.get('items', []))
})

pipeline_total_ok = 119000 <= caller_pipeline.get('total', 0) <= 120500
oz_total_ok = 150 <= oz_default.get('total', 0) <= 300
record('default_bucket_counts_expected_ranges_no_search', pipeline_total_ok and oz_total_ok, {
    'pipeline_total': caller_pipeline.get('total'), 'ozonetel_total': oz_default.get('total')
})

# Search must ignore the bucket and find the raw Ozonetel lead from either tab.
for bucket in ('pipeline', 'ozonetel'):
    r = himani.get(API + '/leads', params={'bucket': bucket, 'search': SEARCH_PHONE, 'page': 1, 'limit': 50}, timeout=60)
    data = parse_json(r)
    found = [it for it in data.get('items', []) if it.get('id') == LEAD_ID]
    record(f'himani_search_{SEARCH_PHONE}_finds_raw_ozonetel_lead_from_{bucket}_bucket', r.status_code == 200 and bool(found) and found[0].get('user_id') == 5, {
        'status': r.status_code, 'total': data.get('total'), 'found_lead': found[0] if found else None
    })

# Broader text search should span both normal pipeline rows and raw Ozonetel rows despite bucket=pipeline.
r = himani.get(API + '/leads', params={'bucket': 'pipeline', 'search': 'Lead 6000', 'page': 1, 'limit': 50}, timeout=60)
span_data = parse_json(r)
span_items = span_data.get('items', [])
raw_ozonetel_ids = [it.get('id') for it in span_items if it.get('ozonetel_lead') is True and it.get('in_pipeline') is not True]
pipeline_ids = [it.get('id') for it in span_items if not (it.get('ozonetel_lead') is True and it.get('in_pipeline') is not True)]
record('search_spans_pipeline_and_raw_ozonetel_rows', r.status_code == 200 and bool(raw_ozonetel_ids) and bool(pipeline_ids), {
    'status': r.status_code, 'total': span_data.get('total'),
    'raw_ozonetel_ids_first_page': raw_ozonetel_ids[:10], 'pipeline_ids_first_page': pipeline_ids[:10]
})

# Detail, cross-caller edits, assignment lock, note/follow-up/caller activity/audit.
r = himani.get(API + f'/leads/{LEAD_ID}', timeout=30)
lead_before = parse_json(r)
record('himani_can_open_lead_600027_owned_by_anamika', r.status_code == 200 and lead_before.get('id') == LEAD_ID and lead_before.get('user_id') == 5 and lead_before.get('original_user_id') == 5, {
    'status': r.status_code, 'id': lead_before.get('id'), 'user_id': lead_before.get('user_id'), 'original_user_id': lead_before.get('original_user_id'),
    'phone': lead_before.get('phone'), 'phone_digits': lead_before.get('phone_digits'), 'pipeline': lead_before.get('pipeline'), 'ozonetel_lead': lead_before.get('ozonetel_lead')
})

r = himani.get(API + '/catalogs', timeout=30)
catalogs = parse_json(r)
stage_names = [s.get('name') for s in catalogs.get('lead_stage', []) if s.get('name')]
tag_ids = [t.get('id') for t in catalogs.get('tag', []) if t.get('active') is not False and t.get('id')]
fu_tags = [t.get('name') for t in catalogs.get('follow_up_tag', []) if t.get('name')]
new_stage = next((s for s in stage_names if s != lead_before.get('lead_stage')), None) or 'Contacted'
tag_to_add = next((tid for tid in tag_ids if tid not in (lead_before.get('tags') or [])), None) or (tag_ids[0] if tag_ids else 1)
new_tags = list(lead_before.get('tags') or [])
if tag_to_add not in new_tags:
    new_tags.append(tag_to_add)

stamp = str(int(time.time()))
new_city = f'QA66 City {stamp}'
patch_payload = {'updates': {
    'city': new_city,
    'lead_stage': new_stage,
    'tags': new_tags,
    'user_id': himani_user.get('id', 8),
    'original_user_id': himani_user.get('id', 8),
}}
r = himani.patch(API + f'/leads/{LEAD_ID}', json=patch_payload, timeout=60)
lead_after_patch = parse_json(r)
record('himani_edits_cross_caller_fields_assignment_stripped', r.status_code == 200 and lead_after_patch.get('city') == new_city and lead_after_patch.get('lead_stage') == new_stage and lead_after_patch.get('user_id') == 5 and lead_after_patch.get('original_user_id') == 5, {
    'status': r.status_code, 'city_after': lead_after_patch.get('city'), 'lead_stage_after': lead_after_patch.get('lead_stage'),
    'tags_after': lead_after_patch.get('tags'), 'user_id_after': lead_after_patch.get('user_id'), 'original_user_id_after': lead_after_patch.get('original_user_id')
})

note_body = f'Iteration 66 cross-caller note by Himani {stamp}'
r_note = himani.post(API + f'/leads/{LEAD_ID}/messages', json={'body': note_body, 'subtype': 'note'}, timeout=30)
note_data = parse_json(r_note)
record('himani_adds_note_on_other_callers_lead', r_note.status_code == 200 and note_body in note_data.get('body', ''), {
    'status': r_note.status_code, 'author_name': note_data.get('author_name'), 'body': note_data.get('body')
})

fu_body = {
    'follow_up_date': (date.today() + timedelta(days=4)).isoformat(),
    'follow_up_time': '11:15',
    'follow_up_tag': (fu_tags[0] if fu_tags else 'Follow UP'),
    'note': f'Iteration 66 cross-caller follow-up by Himani {stamp}',
    'status': 'Pending'
}
r_fu = himani.post(API + f'/leads/{LEAD_ID}/followups', json=fu_body, timeout=30)
fu_data = parse_json(r_fu)
record('himani_adds_followup_on_other_callers_lead', r_fu.status_code == 200 and fu_data.get('created_by') == himani_user.get('id', 8), {
    'status': r_fu.status_code, 'created_by': fu_data.get('created_by'), 'created_by_name': fu_data.get('created_by_name'), 'id': fu_data.get('id')
})

caller_activity_feedback = f'Iteration 66 caller activity by Himani {stamp}'
r_ca = himani.post(API + f'/leads/{LEAD_ID}/caller-activities', json={'feedback': caller_activity_feedback}, timeout=30)
ca_data = parse_json(r_ca)
record('himani_adds_caller_activity_on_other_callers_lead', r_ca.status_code == 200 and ca_data.get('created_by') == himani_user.get('id', 8), {
    'status': r_ca.status_code, 'created_by': ca_data.get('created_by'), 'created_by_name': ca_data.get('created_by_name'), 'id': ca_data.get('id')
})

r_assign = himani.patch(API + f'/leads/{LEAD_ID}', json={'updates': {'user_id': himani_user.get('id', 8), 'original_user_id': himani_user.get('id', 8)}}, timeout=30)
r_after_assign = himani.get(API + f'/leads/{LEAD_ID}', timeout=30)
lead_after_assign = parse_json(r_after_assign)
record('caller_assignment_only_patch_blocked_and_assignment_unchanged', r_assign.status_code == 400 and lead_after_assign.get('user_id') == 5 and lead_after_assign.get('original_user_id') == 5, {
    'patch_status': r_assign.status_code, 'patch_body': parse_json(r_assign),
    'user_id_after': lead_after_assign.get('user_id'), 'original_user_id_after': lead_after_assign.get('original_user_id')
})

r_audit = himani.get(API + f'/leads/{LEAD_ID}/audit', timeout=30)
audits = parse_json(r_audit)
if not isinstance(audits, list):
    audits = []
recent_himani = [a for a in audits if a.get('user_name') == 'Himani Sharma'][:40]
has_city = any(a.get('field') == 'City' and a.get('new') == new_city for a in recent_himani)
has_tag_or_stage = any(a.get('action') in ('disposition_changed', 'stage_changed') and (a.get('user_name') == 'Himani Sharma') for a in recent_himani)
has_note = any(a.get('action') == 'note_added' and stamp in (a.get('detail') or '') for a in recent_himani)
has_fu = any(a.get('action') == 'follow_up_added' and stamp in (a.get('detail') or '') for a in recent_himani)
has_ca = any(a.get('action') == 'caller_activity' and stamp in (a.get('detail') or '') for a in recent_himani)
record('audit_log_records_cross_caller_edits_by_himani', r_audit.status_code == 200 and has_city and has_tag_or_stage and has_note and has_fu and has_ca, {
    'status': r_audit.status_code, 'has_city': has_city, 'has_stage_or_disposition': has_tag_or_stage,
    'has_note': has_note, 'has_followup': has_fu, 'has_caller_activity': has_ca,
    'recent_himani': recent_himani[:10]
})

Path('/app/test_reports/iteration_66_api_results.json').write_text(json.dumps(results, indent=2, default=str, ensure_ascii=False))
print(json.dumps(results, indent=2, default=str, ensure_ascii=False))
raise SystemExit(0 if all(c['ok'] for c in results['checks']) else 1)