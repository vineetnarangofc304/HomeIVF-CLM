# iteration_69_browser_check.py
# Playwright QA script used via mcp_browser_automation for focused rapid-navigation bug verification.
# It logs in as caller16, starts loading /leads/600027, rapidly navigates Leads -> Follow-ups -> WhatsApp -> Leads,
# then asserts the destination page loads without visible Cloudflare/busy/error overlay text.

async def run(page):
    await page.set_viewport_size({"width": 1920, "height": 1080})
    page.set_default_timeout(15000)

    async def page_error_text():
        return await page.evaluate("""() => {
            const bodyText = document.body ? document.body.innerText : '';
            const errorElements = Array.from(document.querySelectorAll('.error, [class*="error"], [id*="error"]'));
            const sonner = Array.from(document.querySelectorAll('[data-sonner-toast], [data-type="error"], [class*="toast"], [class*="sonner"]'));
            return {
                errorText: errorElements.map(el => el.textContent).join(', '),
                toastText: sonner.map(el => el.textContent).join(', '),
                hasCloudflare: /Cloudflare|origin web server|could not parse|HTTP 520|empty response|malformed HTTP headers/i.test(bodyText),
                hasCanceledOverlay: /Uncaught runtime errors|CanceledError: canceled/i.test(bodyText),
                bodySnippet: bodyText.slice(0, 500)
            };
        }""")

    await page.goto('https://ivf-lead-ops.preview.emergentagent.com/login')
    await page.locator('[data-testid="login-email-input"]').fill('caller16@homeivf.com')
    await page.locator('[data-testid="login-password-input"]').fill('TestPass@2026')
    await page.locator('[data-testid="login-submit-button"]').click()
    await page.wait_for_url('**/leads**', timeout=30000)
    await page.locator('[data-testid="leads-table"]').wait_for(state='visible', timeout=30000)

    await page.goto('https://ivf-lead-ops.preview.emergentagent.com/leads/600027')
    await page.wait_for_timeout(80)
    await page.locator('[data-testid="nav-leads"]').click(force=True)
    await page.wait_for_timeout(80)
    await page.locator('[data-testid="nav-followups"]').click(force=True)
    await page.wait_for_timeout(80)
    await page.locator('[data-testid="nav-whatsapp"]').click(force=True)
    await page.wait_for_timeout(80)
    await page.locator('[data-testid="nav-leads"]').click(force=True)
    await page.wait_for_timeout(3000)

    err = await page_error_text()
    assert not err['hasCloudflare'], err
    assert not err['hasCanceledOverlay'], err
    assert not err['toastText'].strip(), err
    await page.locator('[data-testid="leads-table"]').wait_for(state='visible', timeout=30000)
