"""
Focused Playwright verification notes for iteration 78 (HomeIVF CRM pending auth/leads/API pile-up bug).

Executed via MCP browser automation against:
https://ivf-lead-ops.preview.emergentagent.com

Coverage:
- Stalled GET /api/auth/me using a Playwright route that never responded: verified protected /leads left the spinner and showed login within ~12.5s; /auth/me request count was exactly 1 on a single page load.
- Guest no-token path: cleared localStorage/cookies, real /api/auth/me returned 401 once, login screen appeared promptly.
- Normal admin login: admin@homeivf.com / HomeIVF@2026 returned 200, token stored, protected /leads loaded after /auth/me 200.
- Poller regression: delayed /api/calls/active by ~15s; max in-flight was 1; initial pollers (/calls/active, /whatsapp/unread-summary, /leads/followups/reminders, /agent/me) each fired once.
- Leads menu regression: one Leads side-menu click fired exactly one /api/leads list request on mount; /api/filters still fired twice but did not affect the heavy list request.
- Hidden-tab regression: pollers paused while document.hidden=true, refreshed on visible, and /calls/active continued after navigation.
- Stalled /api/leads regression: route was held pending; axios hard timeout surfaced at ~60s with one "Server is busy" toast and one /api/leads attempt.
- Widget regression: IncomingCallBanner, WaNotifier, FollowUpReminder, and AgentStatusSwitcher rendered and interacted using TEST-ONLY route stubs.
- Real admin Leads list + opening a lead worked with real backend data; no "Data failed / API Error / No data response" text appeared.

Notes:
- Product code was not changed.
- TEST-ONLY MOCKED/stubbed network responses were used only to simulate stalled/positive poller conditions required by the regression scenarios.
"""
