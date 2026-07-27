"""
Focused Playwright verification plan for iteration 77 (HomeIVF CRM request pile-up bug).

These snippets were executed with the MCP browser runner against:
https://homeivf-crm-2.preview.emergentagent.com

Covered:
- StrictMode auth bootstrap count and normal admin login
- Module-level no-overlap poller guard with delayed /api/calls/active
- Initial protected-layout poller duplicate counts
- Leads list de-dupe on mount and on filter change
- Pause-when-hidden / resume-on-visible
- Navigation while /calls/active is delayed (no poller deadlock)
- 60s stalled GET /api/leads timeout and friendly toast/no retry
- Conditional poller widget rendering via test route stubs
- Admin leads list and opening a lead

Note: product code was not changed; route stubs/delays here are test-only simulations of slow
or data-positive API responses.
"""

# See the JSON report for the deterministic verdict and summarized measurements.