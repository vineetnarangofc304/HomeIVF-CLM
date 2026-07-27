"""Playwright script body used by browser automation for iteration 74.

This file is a persisted copy of the script passed to mcp_browser_automation.
It focuses only on the reported Leads filter timeout flow.
"""

await page.set_viewport_size({"width": 1920, "height": 1080})
BASE_URL = "https://homeivf-crm-2.preview.emergentagent.com"
responses = []

def on_response(resp):
    url = resp.url
    if "/api/leads" in url or "/api/whatsapp/unread-summary" in url or "/api/calls/active" in url or "/api/reports/dashboard" in url:
        responses.append({"url": url, "status": resp.status})

page.on("response", on_response)

try:
    print("Step 1: open login page")
    await page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
    await page.locator('[data-testid="login-email-input"]').fill("admin@homeivf.com")
    await page.locator('[data-testid="login-password-input"]').fill("HomeIVF@2026")
    await page.locator('[data-testid="login-submit-button"]').click()
    await page.wait_for_selector('[data-testid="nav-leads"]', timeout=20000)
    print("Login succeeded")

    print("Step 2: open Leads page / all pipeline tab")
    await page.locator('[data-testid="nav-leads"]').click()
    await page.wait_for_selector('[data-testid="leads-page"]', timeout=20000)
    await page.wait_for_selector('[data-testid="bucket-pipeline-all"]', timeout=10000)
    await page.locator('[data-testid="bucket-pipeline-all"]').click()
    await page.wait_for_timeout(1200)
    print("Leads page loaded")

    print("Step 3: apply Lead Stage=Contacted and Tag=OPD Booked")
    await page.locator('[data-testid="filter-lead-stage"]').select_option(label="Contacted")
    await page.wait_for_timeout(500)
    await page.locator('[data-testid="filter-tag"]').select_option(label="OPD Booked")
    await page.wait_for_timeout(2500)

    busy_text = await page.get_by_text("Server is busy right now", exact=False).count()
    table_count = await page.locator('[data-testid="leads-table"]').count()
    empty_count = await page.get_by_text("No leads found", exact=True).count()
    total_text = ""
    if await page.locator('[data-testid="leads-total-count"]').count() > 0:
        total_text = await page.locator('[data-testid="leads-total-count"]').inner_text()
    assert busy_text == 0, "Server is busy toast appeared after tag+stage filter"
    assert table_count > 0 or empty_count > 0, "Neither table nor empty state rendered after tag+stage filter"
    filtered_leads_responses = [r for r in responses if "/api/leads?" in r["url"] and "lead_stage=Contacted" in r["url"] and "tags=" in r["url"]]
    assert filtered_leads_responses, "No /api/leads response captured for tag+stage filter"
    assert all(r["status"] == 200 for r in filtered_leads_responses), f"Non-200 leads response for tag+stage filter: {filtered_leads_responses}"
    print(f"Tag+stage filter rendered OK: table_count={table_count}, empty_count={empty_count}, total='{total_text}', responses={filtered_leads_responses[-3:]}")

    print("Step 4: verify pagination works on a populated Leads view")
    await page.locator('[data-testid="filter-tag"]').select_option(value="")
    await page.wait_for_timeout(1800)
    await page.wait_for_selector('[data-testid="leads-table"]', timeout=15000)
    initial_total = await page.locator('[data-testid="leads-total-count"]').inner_text()
    next_button = page.locator('[data-testid="next-page-button"]')
    if await next_button.is_enabled():
        await next_button.click()
        await page.wait_for_timeout(1800)
        page2_total = await page.locator('[data-testid="leads-total-count"]').inner_text()
        assert "page 2" in page2_total, f"Pagination did not move to page 2: {page2_total}"
        print(f"Pagination moved from '{initial_total}' to '{page2_total}'")
    else:
        print(f"Pagination next disabled on populated view; total text='{initial_total}'")

    print("Step 5: click first row and verify lead detail opens")
    await page.wait_for_selector('[data-testid^="lead-row-"]', timeout=15000)
    first_row = page.locator('[data-testid^="lead-row-"]').first
    first_testid = await first_row.get_attribute("data-testid")
    await first_row.click()
    await page.wait_for_selector('[data-testid="lead-detail-page"]', timeout=20000)
    lead_name = await page.locator('[data-testid="lead-name"]').inner_text()
    assert lead_name.strip(), "Lead detail opened but lead name is empty"
    print(f"Lead detail opened from {first_testid}: {lead_name}")

    print("Step 6: force secondary reads to 504 and verify core lead 500210 still renders")
    async def forced_504(route):
        await route.fulfill(status=504, content_type="application/json", body='{"detail":"forced secondary 504"}')
    await page.route("**/api/leads/500210/messages**", forced_504)
    await page.route("**/api/leads/500210/activities**", forced_504)
    await page.route("**/api/whatsapp/lead/500210**", forced_504)
    await page.route("**/api/calls/lead/500210**", forced_504)
    await page.route("**/api/leads/500210/attachments**", forced_504)
    await page.route("**/api/wa/lead/500210/messages**", forced_504)
    await page.goto(f"{BASE_URL}/leads/500210", wait_until="domcontentloaded")
    await page.wait_for_selector('[data-testid="lead-detail-page"]', timeout=20000)
    core_name = await page.locator('[data-testid="lead-name"]').inner_text()
    assert core_name.strip(), "Forced secondary 504s prevented core lead detail from rendering"
    print(f"Lead 500210 core detail rendered despite forced secondary 504s: {core_name}")

    # Get error messages using specific selectors
    error_text = await page.evaluate("""() => {
    const errorElements = Array.from(document.querySelectorAll('.error, [class*="error"], [id*="error"]'));
    return errorElements.map(el => el.textContent).join(", ");
    }""")
    if error_text:
        print(f"Found error message: {error_text}")
    else:
        print("No error messages found on the page")
    print("UI focused flow PASS")
except Exception as e:
    print(f"UI focused flow FAIL: {e}")
    await page.screenshot(path="/app/test_reports/iteration_74_ui_failure.jpg", quality=40, full_page=False)
    raise