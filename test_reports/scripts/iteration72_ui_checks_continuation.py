import re, time

async def login(email, password):
    await page.goto('https://homeivf-crm-2.preview.emergentagent.com/login')
    await page.get_by_test_id('login-email-input').fill(email)
    await page.get_by_test_id('login-password-input').fill(password)
    await page.get_by_test_id('login-submit-button').click()
    await page.wait_for_load_state('networkidle', timeout=20000)
    await page.wait_for_selector('[data-testid="topbar-user-name"]', timeout=20000)
    print(f'PASS login {email}')

async def collect_errors(label):
    error_text = await page.evaluate("""() => {
const errorElements = Array.from(document.querySelectorAll('.error, [class*="error"], [id*="error"]'));
return errorElements.map(el => el.textContent).join(", ");
}""")
    if error_text:
        print(f"Found error message: {error_text}")
    else:
        print("No error messages found on the page")
    busy = await page.locator('text=Server is busy right now').count()
    print(f'{label}: busy_toast_count={busy}')
    return busy

async def wait_leads_loaded(label):
    await page.wait_for_selector('[data-testid="leads-page"]', timeout=20000)
    await page.wait_for_selector('[data-testid="leads-table"]', timeout=20000)
    rows = await page.locator('[data-testid^="lead-row-"]').count()
    footer = await page.get_by_test_id('leads-total-count').inner_text(timeout=10000)
    print(f'PASS {label}: rows={rows}, footer={footer}')
    assert rows > 0
    assert 'leads · page' in footer and (('Many' in footer) or re.search(r'\d', footer))
    assert await collect_errors(label) == 0

try:
    await page.set_viewport_size({'width': 1920, 'height': 1080})
    page.set_default_timeout(20000)

    await login('admin@homeivf.com', 'HomeIVF@2026')

    # UI edit regression: use Case Details / Remark (no mandatory city/state validation).
    await page.goto('https://homeivf-crm-2.preview.emergentagent.com/leads/500210')
    await page.wait_for_selector('[data-testid="lead-detail-page"]', timeout=20000)
    await page.wait_for_selector('[data-testid="field-value-remark"]', timeout=10000)
    original_remark_visible = await page.get_by_test_id('field-value-remark').inner_text(timeout=10000)
    original_restore = '' if original_remark_visible.strip() in ['—', '-'] else original_remark_visible
    new_remark = f'iter72-ui-remark-{int(time.time())}'
    await page.get_by_test_id('edit-case-details').click()
    await page.get_by_test_id('field-input-remark').fill(new_remark)
    await page.get_by_test_id('save-case-details').click()
    await page.wait_for_timeout(1500)
    observed = await page.get_by_test_id('field-value-remark').inner_text(timeout=10000)
    print(f'PASS UI PATCH remark observed={observed}')
    assert observed == new_remark, f'UI remark save failed, observed={observed}'
    # Restore original remark value.
    await page.get_by_test_id('edit-case-details').click()
    await page.get_by_test_id('field-input-remark').fill(original_restore)
    await page.get_by_test_id('save-case-details').click()
    await page.wait_for_timeout(1500)
    restored = await page.get_by_test_id('field-value-remark').inner_text(timeout=10000)
    expected_restored = original_remark_visible if original_restore else '—'
    print(f'PASS UI PATCH remark restored visible={restored}')
    assert restored == expected_restored, f'UI remark restore failed expected={expected_restored} observed={restored}'
    assert await collect_errors('UI edit remark') == 0

    async def fail_secondary(route):
        await route.fulfill(status=504, content_type='application/json', body='{"detail":"forced secondary timeout"}')

    # Direct 600027 with secondary reads forced to 504.
    secondary_patterns_600 = [
        '**/api/leads/600027/messages*', '**/api/leads/600027/activities*', '**/api/whatsapp/lead/600027*',
        '**/api/calls/lead/600027*', '**/api/leads/600027/attachments*', '**/api/leads/600027/followups*',
        '**/api/leads/600027/caller-activities*', '**/api/wa/lead/600027/messages*', '**/api/leads/600027/audit*',
    ]
    for pat in secondary_patterns_600:
        await page.route(pat, fail_secondary)
    await page.goto('https://homeivf-crm-2.preview.emergentagent.com/leads/600027')
    await page.wait_for_selector('[data-testid="lead-detail-page"]', timeout=20000)
    name600 = await page.get_by_test_id('lead-name').inner_text(timeout=10000)
    await page.wait_for_selector('[data-testid="assignee-select"]', timeout=10000)
    print(f'PASS direct lead 600027 rendered despite forced secondary 504s: {name600}')
    assert 'Lead 600027' in name600
    assert await collect_errors('600027 secondary 504 detail') == 0
    for pat in secondary_patterns_600:
        await page.unroute(pat, fail_secondary)

    # Non-lead sections still open.
    await page.goto('https://homeivf-crm-2.preview.emergentagent.com/followups')
    await page.wait_for_selector('[data-testid="followups-page"]', timeout=20000)
    await page.wait_for_selector('[data-testid="followup-analytics"]', timeout=15000)
    print('PASS Follow-ups page opened')
    await page.goto('https://homeivf-crm-2.preview.emergentagent.com/call-center')
    await page.wait_for_selector('[data-testid="call-center-page"]', timeout=20000)
    await page.wait_for_selector('[data-testid="call-list-table"], text=No calls logged yet.', timeout=20000)
    print('PASS Call Center page opened')

    # Caller leads default My and All scope.
    await page.get_by_test_id('logout-button').click()
    await page.wait_for_timeout(1000)
    await login('caller16@homeivf.com', 'TestPass@2026')
    await page.goto('https://homeivf-crm-2.preview.emergentagent.com/leads')
    await wait_leads_loaded('caller default my leads')
    scope_hint_my = await page.get_by_test_id('scope-hint').inner_text(timeout=10000)
    assert 'Viewing your leads' in scope_hint_my
    await page.get_by_test_id('bucket-pipeline-all').click()
    await page.wait_for_timeout(1000)
    await wait_leads_loaded('caller all leads scope')
    scope_hint_all = await page.get_by_test_id('scope-hint').inner_text(timeout=10000)
    assert 'Viewing all callers' in scope_hint_all
    print('PASS caller my/all leads tabs both load')

    print('FINAL PASS iteration72 UI continuation complete')
except Exception as e:
    print(f'FINAL FAIL iteration72 UI continuation: {type(e).__name__}: {e}')
    await page.screenshot(path='/app/test_reports/iteration72_ui_continuation_failure.jpeg', quality=40, full_page=False)
    raise
