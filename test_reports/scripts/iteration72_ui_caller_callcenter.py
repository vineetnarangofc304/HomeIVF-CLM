import re

async def login(email, password):
    await page.goto('https://ivf-lead-ops.preview.emergentagent.com/login')
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
    assert busy == 0

async def wait_leads_loaded(label):
    await page.wait_for_selector('[data-testid="leads-page"]', timeout=20000)
    await page.wait_for_selector('[data-testid="leads-table"]', timeout=20000)
    rows = await page.locator('[data-testid^="lead-row-"]').count()
    footer = await page.get_by_test_id('leads-total-count').inner_text(timeout=10000)
    print(f'PASS {label}: rows={rows}, footer={footer}')
    assert rows > 0
    assert 'leads · page' in footer and (('Many' in footer) or re.search(r'\d', footer))
    await collect_errors(label)

try:
    await page.set_viewport_size({'width': 1920, 'height': 1080})
    page.set_default_timeout(20000)

    # Reconfirm Call Center page with corrected selector.
    await login('admin@homeivf.com', 'HomeIVF@2026')
    await page.goto('https://ivf-lead-ops.preview.emergentagent.com/call-center')
    await page.wait_for_selector('[data-testid="call-center-page"]', timeout=20000)
    table_count = await page.get_by_test_id('call-list-table').count()
    empty_count = await page.get_by_text('No calls logged yet.').count()
    assert table_count > 0 or empty_count > 0, 'Call Center content did not render'
    print(f'PASS Call Center page opened with table_count={table_count}, empty_count={empty_count}')
    await collect_errors('call center')

    # Caller: default My leads and explicit All scope both render rows and no busy toast.
    await page.get_by_test_id('logout-button').click()
    await page.wait_for_timeout(1000)
    await login('caller16@homeivf.com', 'TestPass@2026')
    await page.goto('https://ivf-lead-ops.preview.emergentagent.com/leads')
    await wait_leads_loaded('caller default my leads')
    scope_hint_my = await page.get_by_test_id('scope-hint').inner_text(timeout=10000)
    assert 'Viewing your leads' in scope_hint_my, f'wrong default scope hint: {scope_hint_my}'
    await page.get_by_test_id('bucket-pipeline-all').click()
    await page.wait_for_timeout(1000)
    await wait_leads_loaded('caller all leads scope')
    scope_hint_all = await page.get_by_test_id('scope-hint').inner_text(timeout=10000)
    assert 'Viewing all callers' in scope_hint_all, f'wrong all scope hint: {scope_hint_all}'
    print('PASS caller my/all leads tabs both load')

    print('FINAL PASS iteration72 caller/callcenter UI complete')
except Exception as e:
    print(f'FINAL FAIL iteration72 caller/callcenter UI: {type(e).__name__}: {e}')
    await page.screenshot(path='/app/test_reports/iteration72_ui_caller_callcenter_failure.jpeg', quality=40, full_page=False)
    raise
