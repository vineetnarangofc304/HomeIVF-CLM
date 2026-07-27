import requests, time, json, sys
BASE = 'https://homeivf-crm-2.preview.emergentagent.com/api'
ADMIN = ('admin@homeivf.com', 'HomeIVF@2026')
CALLER = ('caller16@homeivf.com', 'TestPass@2026')

def login(creds):
    s = requests.Session()
    t0 = time.perf_counter()
    r = s.post(f'{BASE}/auth/login', json={'email': creds[0], 'password': creds[1]}, timeout=20)
    dt = time.perf_counter() - t0
    r.raise_for_status()
    token = r.json().get('access_token')
    s.headers.update({'Authorization': f'Bearer {token}'})
    return s, dt, r.json()

def timed_get(s, path, params=None, timeout=25):
    t0 = time.perf_counter()
    r = s.get(f'{BASE}{path}', params=params or {}, timeout=timeout)
    dt = time.perf_counter() - t0
    try:
        data = r.json()
    except Exception:
        data = r.text[:500]
    return r.status_code, dt, data, r.url

def timed_patch(s, path, payload, timeout=25):
    t0 = time.perf_counter()
    r = s.patch(f'{BASE}{path}', json=payload, timeout=timeout)
    dt = time.perf_counter() - t0
    try:
        data = r.json()
    except Exception:
        data = r.text[:500]
    return r.status_code, dt, data

out = {'base': BASE, 'steps': []}
admin, admin_login_dt, admin_user = login(ADMIN)
out['steps'].append({'step': 'admin_login', 'seconds': admin_login_dt, 'user': {k: admin_user.get(k) for k in ['id','email','role']}})
caller, caller_login_dt, caller_user = login(CALLER)
out['steps'].append({'step': 'caller_login', 'seconds': caller_login_dt, 'user': {k: caller_user.get(k) for k in ['id','email','role']}})

# Expire backend in-memory count cache so the next default list call proves cold-cache behavior.
time.sleep(32)
params_admin = {'bucket': 'pipeline', 'page': 1, 'limit': 50, 'sort': 'create_date', 'order': 'desc'}
for label in ['admin_leads_cold_after_ttl', 'admin_leads_second_same_filter']:
    code, dt, data, url = timed_get(admin, '/leads', params_admin)
    out['steps'].append({'step': label, 'status': code, 'seconds': dt, 'url': url, 'items': len(data.get('items', [])) if isinstance(data, dict) else None, 'total': data.get('total') if isinstance(data, dict) else None, 'first_ids': [x.get('id') for x in data.get('items', [])[:3]] if isinstance(data, dict) else None})
    if label.endswith('ttl'):
        time.sleep(1.0)

# Caller default My leads and explicit All scope.
for label, params in [
    ('caller_default_my_leads', {'bucket':'pipeline','page':1,'limit':50,'sort':'create_date','order':'desc'}),
    ('caller_all_scope', {'bucket':'pipeline','scope':'all','page':1,'limit':50,'sort':'create_date','order':'desc'}),
]:
    code, dt, data, url = timed_get(caller, '/leads', params)
    out['steps'].append({'step': label, 'status': code, 'seconds': dt, 'url': url, 'items': len(data.get('items', [])) if isinstance(data, dict) else None, 'total': data.get('total') if isinstance(data, dict) else None, 'first_ids': [x.get('id') for x in data.get('items', [])[:3]] if isinstance(data, dict) else None})

for lid in [500210, 600027]:
    code, dt, data, url = timed_get(admin, f'/leads/{lid}')
    out['steps'].append({'step': f'admin_get_lead_{lid}', 'status': code, 'seconds': dt, 'url': url, 'id': data.get('id') if isinstance(data, dict) else None, 'name': (data.get('contact_name') or data.get('name')) if isinstance(data, dict) else None})

# Regression PATCH: update then restore a harmless field.
code, dt, data, url = timed_get(admin, '/leads/500210')
orig = data.get('remark') if isinstance(data, dict) else None
new_val = f'iter72-save-check-{int(time.time())}'
code1, dt1, data1 = timed_patch(admin, '/leads/500210', {'updates': {'remark': new_val}})
code2, dt2, data2, _ = timed_get(admin, '/leads/500210')
restore_status = None
if code1 == 200:
    restore_status, restore_dt, restore_data = timed_patch(admin, '/leads/500210', {'updates': {'remark': orig or ''}})
else:
    restore_dt = None
out['steps'].append({'step': 'admin_patch_lead_500210_remark_then_restore', 'patch_status': code1, 'patch_seconds': dt1, 'readback_status': code2, 'readback_seconds': dt2, 'saved_value_observed': data2.get('remark') if isinstance(data2, dict) else None, 'restore_status': restore_status, 'restore_seconds': restore_dt})

# Non-leads regression backend endpoints used by Follow-ups and Call Center pages.
for label, path, params in [
    ('followups_list_today', '/leads', {'follow_up':'today','limit':100,'sort':'follow_up_date','order':'asc'}),
    ('activities_today', '/activities', {'when':'today','scope':'my'}),
    ('calls_list', '/calls', {'limit':100}),
]:
    code, dt, data, url = timed_get(admin, path, params)
    out['steps'].append({'step': label, 'status': code, 'seconds': dt, 'url': url, 'items': len(data.get('items', [])) if isinstance(data, dict) and isinstance(data.get('items'), list) else (len(data) if isinstance(data, list) else None), 'total': data.get('total') if isinstance(data, dict) else None})

# Assertions with generous preview thresholds; user-visible contract is HTTP 200 with rows and no timeout/busy error.
failures = []
for st in out['steps']:
    if st['step'] in ['admin_leads_cold_after_ttl', 'admin_leads_second_same_filter', 'caller_default_my_leads', 'caller_all_scope']:
        if st['status'] != 200 or not st['items'] or st['seconds'] > 5:
            failures.append(f"{st['step']} did not return 200 with rows quickly: {st}")
    if st['step'] == 'admin_leads_second_same_filter':
        if not isinstance(st.get('total'), int) or st['total'] < 0:
            failures.append(f"second same filter did not return cached exact total: {st}")
    if st['step'].startswith('admin_get_lead_'):
        if st['status'] != 200 or not st.get('name') or st['seconds'] > 5:
            failures.append(f"{st['step']} did not load core record quickly: {st}")
    if st['step'] == 'admin_patch_lead_500210_remark_then_restore':
        if st['patch_status'] != 200 or st['readback_status'] != 200 or st['saved_value_observed'] != new_val or st['restore_status'] != 200:
            failures.append(f"PATCH/save regression failed: {st}")
    if st['step'] in ['followups_list_today','activities_today','calls_list']:
        if st['status'] != 200 or st['seconds'] > 8:
            failures.append(f"Non-leads regression endpoint slow/failing: {st}")
out['failures'] = failures
print(json.dumps(out, indent=2))
sys.exit(1 if failures else 0)
