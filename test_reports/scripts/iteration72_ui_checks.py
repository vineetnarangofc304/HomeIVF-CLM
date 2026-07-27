# Playwright script body for mcp_browser_automation (executed inside async function with `page`).
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
        print(f"Found error message after {label}: {error_text}")
    else:
        print(f"No error messages found on the page after {label}")
    busy = await page.locator('text=Server is busy right now').count()
    print(f'{label}: busy_toast_count={busy}')
    return error_text, busy

async def wait_leads_loaded(label):
    await page.wait_for_selector('[data-testid="leads-page"]', timeout=20000)
    await page.wait_for_selector('[data-testid="leads-table"]', timeout=20000)
    rows = await page.locator('[data-testid^="lead-row-"]').count()
    footer = await page.get_by_test_id('leads-total-count').inner_text(timeout=10000)
    print(f'PASS {label}: rows={rows}, footer={footer}')
    assert rows > 0, f'{label} had no lead rows'
    assert ('leads · page' in footer) and (('Many' in footer) or re.search(r'\d', footer)), f'bad pagination footer: {footer}'
    err, busy = await collect_errors(label)
    assert busy == 0, f'{label} showed server busy toast'
    return rows, footer

try:
    await page.set_viewport_size({'width': 1920, 'height': 1080})
    page.set_default_timeout(20000)

    # Admin: list opens with rows and pagination works; row-click opens lead detail.
    await login('admin@homeivf.com', 'HomeIVF@2026')
    await page.get_by_test_id('nav-leads').click()
    await wait_leads_loaded('admin leads first load')
    await page.get_by_test_id('next-page-button').click()
    await page.wait_for_timeout(800)
    footer2 = await page.get_by_test_id('leads-total-count').inner_text(timeout=10000)
    print(f'PASS admin next page clicked: footer={footer2}')
    assert 'page 2' in footer2, 'Next pagination did not move to page 2'
    await page.get_by_test_id('prev-page-button').click()
    await page.wait_for_timeout(800)
    assert 'page 1' in await page.get_by_test_id('leads-total-count').inner_text(), 'Prev pagination did not return to page 1'

    # Row click: first row should be a valid lead and detail must render.
    await page.locator('[data-testid^="lead-row-"]').first.click()
    await page.wait_for_selector('[data-testid="lead-detail-page"]', timeout=20000)
    lead_name = await page.get_by_test_id('lead-name').inner_text(timeout=10000)
    await page.wait_for_selector('[data-testid="assignee-select"]', timeout=10000)
    print(f'PASS row-click lead detail opened: lead_name={lead_name}')
    err, busy = await collect_errors('admin row-click lead detail')
    assert busy == 0, 'row-click lead detail showed server busy toast'

    # Admin direct 500210 detail with secondary reads forced to 504; core should render.
    secondary_patterns = [
        '**/api/leads/500210/messages*', '**/api/leads/500210/activities*', '**/api/whatsapp/lead/500210*',
        '**/api/calls/lead/500210*', '**/api/leads/500210/attachments*', '**/api/leads/500210/followups*',
        '**/api/leads/500210/caller-activities*', '**/api/wa/lead/500210/messages*', '**/api/leads/500210/audit*',
    ]
    async def fail_secondary(route):
        await route.fulfill(status=504, content_type='application/json', body='{"detail":"forced secondary timeout"}')
    for pat in secondary_patterns:
        await page.route(pat, fail_secondary)
    await page.goto('https://homeivf-crm-2.preview.emergentagent.com/leads/500210')
    await page.wait_for_selector('[data-testid="lead-detail-page"]', timeout=20000)
    name500 = await page.get_by_test_id('lead-name').inner_text(timeout=10000)
    await page.wait_for_selector('[data-testid="assignee-select"]', timeout=10000)
    print(f'PASS direct lead 500210 rendered despite forced secondary 504s: {name500}')
    assert 'Fallback Test' in name500, f'unexpected 500210 name {name500}'
    err, busy = await collect_errors('500210 secondary 504 detail')
    # Secondary 504s should be swallowed; no busy toast should appear for core-open success.
    assert busy == 0, 'secondary 504s surfaced Server busy toast on detail open'

    # Regression: edit a field through UI then restore.
    original_name = await page.get_by_test_id('field-value-contact_name').inner_text(timeout=10000)
    new_name = f'Fallback Test UI72 {int(time.time())}'
    await page.get_by_test_id('edit-contact').click()
    await page.get_by_test_id('field-input-contact_name').fill(new_name)
    await page.get_by_test_id('save-contact').click()
    await page.wait_for_timeout(1200)
    observed = await page.get_by_test_id('field-value-contact_name').inner_text(timeout=10000)
    print(f'PASS edit lead contact name save observed={observed}')
    assert observed == new_name, 'UI edit did not save/read back changed contact_name'
    await page.get_by_test_id('edit-contact').click()
    await page.get_by_test_id('field-input-contact_name').fill(original_name)
    await page.get_by_test_id('save-contact').click()
    await page.wait_for_timeout(1200)
    restored = await page.get_by_test_id('field-value-contact_name').inner_text(timeout=10000)
    assert restored == original_name, f'Failed to restore contact_name, observed {restored}'
    print('PASS restored contact name after UI edit regression')

    # Remove routes before testing 600027 and other sections.
    for pat in secondary_patterns:
        await page.unroute(pat, fail_secondary)

    # Direct 600027 with its secondary reads forced to 504.
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
    assert 'Lead 600027' in name600, f'unexpected 600027 name {name600}'
    err, busy = await collect_errors('600027 secondary 504 detail')
    assert busy == 0, 'secondary 504s surfaced Server busy toast on 600027 detail open'
    for pat in secondary_patterns_600:
        await page.unroute(pat, fail_secondary)

    # Follow-ups and Call Center still open (non-leads sections).
    await page.goto('https://homeivf-crm-2.preview.emergentagent.com/followups')
    await page.wait_for_selector('[data-testid="followups-page"]', timeout=20000)
    await page.wait_for_selector('[data-testid="followup-analytics"]', timeout=15000)
    print('PASS Follow-ups page opened')
    await page.goto('https://homeivf-crm-2.preview.emergentagent.com/call-center')
    await page.wait_for_selector('[data-testid="call-center-page"]', timeout=20000)
    await page.wait_for_selector('[data-testid="call-list-table"], text=No calls logged yet.', timeout=20000)
    print('PASS Call Center page opened')

    # Caller: default My leads and All scope both load.
    await page.get_by_test_id('logout-button').click()
    await page.wait_for_timeout(1000)
    await login('caller16@homeivf.com', 'TestPass@2026')
    await page.goto('https://homeivf-crm-2.preview.emergentagent.com/leads')
    await wait_leads_loaded('caller default my leads')
    scope_hint_my = await page.get_by_test_id('scope-hint').inner_text(timeout=10000)
    assert 'Viewing your leads' in scope_hint_my, f'caller default not my leads: {scope_hint_my}'
    await page.get_by_test_id('bucket-pipeline-all').click()
    await page.wait_for_timeout(1000)
    await wait_leads_loaded('caller all leads scope')
    scope_hint_all = await page.get_by_test_id('scope-hint').inner_text(timeout=10000)
    assert 'Viewing all callers' in scope_hint_all, f'caller all scope hint wrong: {scope_hint_all}'
    print('PASS caller my/all leads tabs both load')

    print('FINAL PASS iteration72 UI checks complete')
except Exception as e:
    print(f'FINAL FAIL iteration72 UI checks: {type(e).__name__}: {e}')
    await page.screenshot(path='/app/test_reports/iteration72_ui_failure.jpeg', quality=40, full_page=False)
    raise
