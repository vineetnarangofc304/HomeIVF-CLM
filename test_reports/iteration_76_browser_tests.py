# iteration_76_browser_tests.py
# Focused Playwright checks executed via mcp_browser_automation for the HomeIVF CRM pending API/poller bug.
# The full scripts were run by the testing tool; this file records deterministic repro evidence.

TEST PLAN
- Mandatory skill lookup: search_skills('pending API calls pollers auth me leads timeout') returned no relevant testing skill.
- Inspect changed frontend files: usePoll.js, api.js, AuthContext.jsx, IncomingCallBanner.jsx, WaNotifier.jsx, FollowUpReminder.jsx, AgentStatusSwitcher.jsx.
- Use preview origin https://ivf-lead-ops.preview.emergentagent.com with admin@homeivf.com / HomeIVF@2026.

EXECUTED CHECKS
1) NO-OVERLAP POLLING
   Route: **/api/calls/active* delayed 15s.
   Result: FAIL. starts=2, max_inflight=2 before first delayed response completed.

2) PAUSE-WHEN-HIDDEN
   Simulated document.hidden=true/visibilityState=hidden and waited 35s.
   Result: PASS. No new requests to calls/active, whatsapp/unread-summary, followups/reminders, or agent/me while hidden; pollers resumed when visible.

3) GET CLIENT TIMEOUT
   Route: **/api/leads* list reads stalled 75s.
   Result: PARTIAL/FAIL. Friendly 'Server is busy' toast appeared at ~60.1s and UI stayed responsive, but two identical /api/leads list requests started and produced duplicate toasts.

4) AUTH BOOTSTRAP RESILIENCE
   Stalled **/api/auth/me* after storing a valid token.
   Result: PASS for user-visible fallback. Login screen appeared in ~51.4s; however interception saw duplicate attempts per retry.

5) NORMAL REGRESSION SMOKE
   Result: PASS. Login loaded protected layout, Leads page loaded normally (Many leads · page 1 of 2), first lead opened, agent status changed to Available.
