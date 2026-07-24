"""Reference browser-check script for iteration 68.

Executed via mcp_browser_automation on 2026-07-24 against preview URL.
It verifies the exact UI portions of the production slowness regression fix:
admin/caller Leads tabs, URL/count changes, global search for lead 600027,
and caller assignment lock + Activity Log visibility.
"""

# This file is intentionally a record of the Playwright actions run by the
# browser automation tool, not a standalone pytest. See iteration_68.json for results.

BROWSER_CHECK_SUMMARY = {
    "url": "https://ivf-lead-ops.preview.emergentagent.com",
    "passed": True,
    "checks": [
        "Admin tabs shown: Leads in Pipeline (All), Leads in Pipeline (My leads), Ozonetel Lead",
        "Admin default list count displayed as 1,19,813 and My leads as 0",
        "Caller tabs shown: My leads, All, Ozonetel Lead",
        "Caller default My leads count displayed as 5,144; All displayed as 1,19,813",
        "Caller search 5770614172 from default tab found lead row 600027",
        "Lead 600027 detail showed disabled assignee select and original caller lock for Anamika Suman",
        "Activity Log tab displayed Himani Sharma entries",
        "No page error messages detected",
    ],
}