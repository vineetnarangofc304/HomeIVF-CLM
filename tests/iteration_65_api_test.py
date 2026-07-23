#!/usr/bin/env python3
import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

FRONTEND_ENV = Path('/app/frontend/.env').read_text().splitlines()
BASE = None
for line in FRONTEND_ENV:
    if line.startswith('REACT_APP_BACKEND_URL='):
        BASE = line.split('=', 1)[1].strip().rstrip('/')
        break
assert BASE, 'REACT_APP_BACKEND_URL not found'
API = BASE + '/api'

CREDS = {
    'admin': ('admin@homeivf.com', 'HomeIVF@2026'),
    'himani': ('caller16@homeivf.com', 'TestPass@2026'),
    'anamika': ('caller11@homeivf.com', 'TestPass@2026'),
}

results = {'base_url': BASE, 'checks': []}


def record(name, ok, details):
    results['checks'].append({'name': name, 'ok': bool(ok), 'details': details})
    print(('PASS' if ok else 'FAIL') + ' - ' + name + ': ' + json.dumps(details, default=str))


def login(label):
    s = requests.Session()
    email, pw = CREDS[label]
    r = s.post(API + '/auth/login', json={'email': email, 'password': pw}, timeout=30)
    detail = {'status': r.status_code, 'email': email}
    try:
        detail['body'] = r.json()
    except Exception:
        detail['body'] = r.text[:300]
    record(f'login_{label}', r.status_code == 200, detail)
    if r.status_code == 200:
        token = detail['body'].get('access_token')
        if token:
            s.headers.update({'Authorization': f'Bearer {token}'})
    return s, detail


admin, admin_login = login('admin')
himani, himani_login = login('himani')
anamika, anamika_login = login('anamika')

if not (admin_login.get('status') == 200 and himani_login.get('status') == 200):
    Path('/app/test_reports/iteration_65_api_results.json').write_text(json.dumps(results, indent=2))
    raise SystemExit(2)

# Admin reference total.
r = admin.get(API + '/leads', params={'bucket': 'pipeline', 'page': 1, 'limit': 50}, timeout=60)
admin_data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
record('admin_default_all_leads_reference', r.status_code == 200 and admin_data.get('total', 0) > 100000, {
    'status': r.status_code, 'total': admin_data.get('total'), 'item_count': len(admin_data.get('items', []))
})

# Caller default total must match admin/unscoped and page must include multiple caller IDs.
r = himani.get(API + '/leads', params={'bucket': 'pipeline', 'page': 1, 'limit': 50}, timeout=60)
caller_all = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
caller_ids = sorted({it.get('user_id') for it in caller_all.get('items', []) if it.get('user_id') is not None})
record('himani_default_pipeline_all_leads_unscoped', r.status_code == 200 and caller_all.get('total') == admin_data.get('total') and len(caller_ids) > 1, {
    'status': r.status_code, 'caller_total': caller_all.get('total'), 'admin_total': admin_data.get('total'),
    'distinct_user_ids_on_page': caller_ids[:20]
})

# My leads filter user_id=8 should be far smaller and only own leads.
r = himani.get(API + '/leads', params={'bucket': 'pipeline', 'page': 1, 'limit': 50, 'user_id': 8}, timeout=60)
my_data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
my_ids = sorted({it.get('user_id') for it in my_data.get('items', []) if it.get('user_id') is not None})
record('himani_my_leads_filter_only_own', r.status_code == 200 and 0 < my_data.get('total', 0) < caller_all.get('total', 0) and set(my_ids).issubset({8}), {
    'status': r.status_code, 'total': my_data.get('total'), 'distinct_user_ids_on_page': my_ids
})

# Search another caller's lead by hidden phone_digits.
r = himani.get(API + '/leads', params={'bucket': 'pipeline', 'search': '5770614172', 'page': 1, 'limit': 50}, timeout=60)
search_data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
found = [it for it in search_data.get('items', []) if it.get('id') == 600027]
record('himani_searches_another_callers_phone_finds_lead_600027', r.status_code == 200 and bool(found), {
    'status': r.status_code, 'total': search_data.get('total'), 'found_lead': found[0] if found else None
})

# Detail lead and ownership lock data.
r = himani.get(API + '/leads/600027', timeout=30)
lead_before = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
record('himani_opens_anamika_lead_detail', r.status_code == 200 and lead_before.get('id') == 600027 and lead_before.get('user_id') == 5, {
    'status': r.status_code, 'id': lead_before.get('id'), 'user_id': lead_before.get('user_id'),
    'original_user_id': lead_before.get('original_user_id'), 'city': lead_before.get('city'),
    'lead_stage': lead_before.get('lead_stage'), 'tags': lead_before.get('tags')
})

stamp = str(int(time.time()))
new_city = f'QA City 65 {stamp}'
old_stage = lead_before.get('lead_stage')
new_stage = 'Contacted' if old_stage != 'Contacted' else 'Contact Attempt'
old_tags = lead_before.get('tags') or []
new_tags = list(old_tags)
if 1 not in new_tags:
    new_tags.append(1)
else:
    new_tags = [t for t in new_tags if t != 1] or [2]

patch_payload = {'updates': {
    'city': new_city,
    'lead_stage': new_stage,
    'tags': new_tags,
    'user_id': 8,
    'original_user_id': 8,
}}
r = himani.patch(API + '/leads/600027', json=patch_payload, timeout=60)
lead_after_patch = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
record('himani_edits_other_callers_lead_but_assignment_stripped', r.status_code == 200 and lead_after_patch.get('city') == new_city and lead_after_patch.get('lead_stage') == new_stage and lead_after_patch.get('user_id') == 5 and lead_after_patch.get('original_user_id') == lead_before.get('original_user_id'), {
    'status': r.status_code, 'city_after': lead_after_patch.get('city'), 'lead_stage_after': lead_after_patch.get('lead_stage'),
    'tags_after': lead_after_patch.get('tags'), 'user_id_after': lead_after_patch.get('user_id'),
    'original_user_id_after': lead_after_patch.get('original_user_id')
})

# Add note and follow-up as Himani.
note_body = f'Iteration 65 cross-caller note by Himani {stamp}'
r_note = himani.post(API + '/leads/600027/messages', json={'body': note_body, 'subtype': 'note'}, timeout=30)
note_json = r_note.json() if r_note.headers.get('content-type', '').startswith('application/json') else {}
record('himani_adds_note_on_other_callers_lead', r_note.status_code == 200 and note_body in note_json.get('body', ''), {
    'status': r_note.status_code
})
fu_body = {
    'follow_up_date': (date.today() + timedelta(days=3)).isoformat(),
    'follow_up_time': '10:30',
    'follow_up_tag': 'Follow UP',
    'note': f'Iteration 65 cross-caller follow-up by Himani {stamp}',
    'status': 'Pending'
}
r_fu = himani.post(API + '/leads/600027/followups', json=fu_body, timeout=30)
fu_json = r_fu.json() if r_fu.headers.get('content-type', '').startswith('application/json') else {}
record('himani_adds_followup_on_other_callers_lead', r_fu.status_code == 200 and fu_json.get('created_by') == 8, {
    'status': r_fu.status_code, 'created_by': fu_json.get('created_by')
})

# Attempt assignment-only patch should not change assignment and should be rejected as no valid fields after stripping.
r_assign = himani.patch(API + '/leads/600027', json={'updates': {'user_id': 8, 'original_user_id': 8}}, timeout=30)
r_check = himani.get(API + '/leads/600027', timeout=30)
lead_after_assign_attempt = r_check.json() if r_check.headers.get('content-type', '').startswith('application/json') else {}
record('caller_assignment_only_patch_blocked_and_assignment_unchanged', r_assign.status_code == 400 and lead_after_assign_attempt.get('user_id') == 5 and lead_after_assign_attempt.get('original_user_id') == lead_before.get('original_user_id'), {
    'patch_status': r_assign.status_code, 'patch_body': (r_assign.json() if r_assign.headers.get('content-type', '').startswith('application/json') else r_assign.text[:200]),
    'user_id_after': lead_after_assign_attempt.get('user_id'), 'original_user_id_after': lead_after_assign_attempt.get('original_user_id')
})

# Audit must include Himani field/tag/note/follow-up edits.
r = himani.get(API + '/leads/600027/audit', timeout=30)
audits = r.json() if r.headers.get('content-type', '').startswith('application/json') else []
recent = [a for a in audits if a.get('user_name') == 'Himani Sharma'][:20]
has_city = any(a.get('field') == 'City' and a.get('new') == new_city for a in recent)
has_note = any(a.get('action') == 'note_added' and note_body[:80] in (a.get('detail') or '') for a in recent)
has_fu = any(a.get('action') == 'follow_up_added' and stamp in (a.get('detail') or '') for a in recent)
record('audit_log_records_cross_caller_edits_by_himani', r.status_code == 200 and has_city and has_note and has_fu, {
    'status': r.status_code, 'has_city': has_city, 'has_note': has_note, 'has_followup': has_fu,
    'recent_himani': recent[:8]
})

Path('/app/test_reports/iteration_65_api_results.json').write_text(json.dumps(results, indent=2, default=str))
print(json.dumps(results, indent=2, default=str))
raise SystemExit(0 if all(c['ok'] for c in results['checks']) else 1)