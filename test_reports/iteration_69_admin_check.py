# iteration_69_admin_check.py
# Admin rapid Dashboard -> Leads -> Dashboard smoke check used via mcp_browser_automation.

async def run(page):
    await page.set_viewport_size({"width": 1920, "height": 1080})
    await page.goto('https://homeivf-crm-1.preview.emergentagent.com/login')
    await page.locator('[data-testid="login-email-input"]').fill('admin@homeivf.com')
    await page.locator('[data-testid="login-password-input"]').fill('HomeIVF@2026')
    await page.locator('[data-testid="login-submit-button"]').click()
    await page.wait_for_timeout(100)
    await page.locator('[data-testid="nav-leads"]').click(force=True)
    await page.locator('[data-testid="leads-table"]').wait_for(state='visible', timeout=30000)
    await page.locator('[data-testid="nav-dashboard"]').click(force=True)
    await page.locator('[data-testid="dashboard-page"]').wait_for(state='visible', timeout=30000)
    await page.locator('[data-testid="kpi-total-leads"]').wait_for(state='visible', timeout=30000)
