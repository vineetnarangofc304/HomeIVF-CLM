# Iteration 70 Focused Bug Verification Test Plan

No relevant testing skill found.

Exact user bug: tab/menu navigation while current CRM page is still loading causes an immediate Cloudflare/app error, React CanceledError overlay, and app hang/freezes.

Affected flows to test:
- Caller rapid navigation: Leads -> lead 600027 while loading -> Leads -> Follow-ups -> WhatsApp -> Leads, repeated bursts.
- Admin rapid navigation from Dashboard landing to Leads, then Leads/Dashboard/Reports/Dashboard.
- Inside lead 600027, interrupt activity/WhatsApp data loads and navigate menu pages.

Changed files inspected:
- /app/frontend/src/lib/api.js (global GET registry, route aborts, transient retry, cancellation now returns never-settling promise)
- /app/frontend/src/App.js (RouteChangeAborter + unhandledrejection guard)
- /app/frontend/src/pages/Dashboard.jsx, Leads.jsx, LeadDetail.jsx; also FollowUps.jsx and WhatsAppInbox.jsx for cancellation-prone uncaught GETs.

Direct proof needed for fixed verdict:
- During deliberately slowed GETs and rapid route changes: no React error overlay, no visible CanceledError, no error toast, browser remains interactive.
- Final destination data renders after burst: Leads table and footer count; dashboard KPIs/panels; Follow-ups list/empty state; WhatsApp inbox.
- Regression spot checks: caller default/all lead counts; global search opens 600027; assignee lock/original owner visible; edit/note succeeds; admin lead tabs visible.

Edge cases:
- Pages with uncaught GET promises (FollowUps/WhatsApp) during navigation.
- Lead detail multiple parallel GETs and nested tab GETs.
- Intended mandatory-field navigation guard after editing a lead is not considered this bug.
