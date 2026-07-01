# HomeIVF CRM — PRD

## Original Problem Statement
HomeIVF (homeivf.com, at-home IVF fertility care, venture of Seeds of Innocens) runs its entire CRM/lead management/follow-up/conversion cycle on Odoo (homeivf.odoo.com, Odoo 19 Enterprise SaaS). They want a fully-owned custom CRM ("HomeIVF CRM", to be hosted on homeivfcrm.com, branded "Powered by TagQuest") that:
- **Phase 1**: Replicates ALL Odoo functionality they use — interfaces, flows, workflows, reports with filters/dropdowns, full backend admin — with FULL data migration.
- **Phase 2**: AI insights + AI recommendations on every section, plus an "AI Brain" conversational analytics chat (Emergent LLM key approved by user).

## User Choices (confirmed)
- Keep duplicate Odoo Studio fields AS-IS (raw under `lead.custom`); cleanup deferred to Phase 2. Convenience coalesced fields (lead_stage, follow_up_date, gender, etc.) computed at migration on top.
- Full migration incl. chatter + WhatsApp history.
- Live API creds (Meta WhatsApp, MyOperator auto-caller, SMTP email) will be provided LATER — build ready-to-connect (outbound_queue with status pending_api_credentials).
- Roles: Admin / Manager / Caller (callers see only own leads). JWT email/password auth, admin-managed users.

## The Business (from Odoo discovery)
Tele-calling lead engine: 27 users (24 callers + managers), 99,516 leads, 96K contacts, 10,936 WhatsApp conversations, 55 WA templates, 32 email templates, 16 automations, ~910K lead chatter messages.
Actual workflow: custom **Lead Stage** (Contact Attempt → Contacted → Converted → Closed) + **34 disposition tags** (Ringing, Busy, OPD Booked, OPD Done, Registration Done, Treatment Started, Junk...) + **Follow Up Date/Tag (Follow UP 1-5)**. Leads arrive via webhooks (landing pages/chatbot/website/app/callback) with questionnaire + ads attribution. Reports = group-bys of Caller × Tags × Day/Month.

## Architecture
- FastAPI + MongoDB (motor) + React (CRA, Tailwind, phosphor icons, recharts). Supervisor-managed.
- Backend: /app/backend/server.py (app+startup seed/indexes), core/ (db, security, utils incl. automation engine), routes/ (auth, users, leads, chatter, catalogs, templates, whatsapp, reports, webhooks, filters, admin), migration/odoo_migrate.py (resumable ETL, checkpoints in migration_status).
- Integer `id` fields everywhere (Odoo ids preserved for migrated data; counters for new: leads from 500000, messages 5M, users 1000).
- Collections: users, leads (custom dict holds raw x_studio fields), messages (lead chatter), activities, catalogs (type-scoped: tag/stage/lost_reason/lead_stage/follow_up_tag/utm_*/activity_type/source_lead), templates_email, templates_whatsapp, wa_channels, wa_messages, contacts, webhooks, automations, saved_filters, saved_filters_odoo (raw), settings, outbound_queue, migration_status, counters, login_attempts.
- Dates stored as "YYYY-MM-DD HH:MM:SS" UTC strings + create_date_ist for IST day/month grouping.
- Odoo creds in backend/.env (ODOO_URL/DB/LOGIN/PASSWORD) for migration.

## New cases 18-24 (2026-07-01, batch 17) — verified iteration_12 (10/10 backend, frontend 100%)
- **Case 18 Dashboard date filter**: `/reports/dashboard?date_from&date_to` scopes funnel/chart/leaderboard/tags; default (no range) keeps all-time funnel. UI date pickers + Clear + "In range" summary.
- **Case 19 Follow-up time**: added `follow_up_time` field (EDITABLE_FIELDS + LeadCreate + list projection) + time input in LeadDetail follow-up section.
- **Case 20 Duplicate flag**: `check_duplicate()` by phone_digits (active leads) on all 3 creation paths (manual/webhook/facebook); sets is_duplicate + duplicate_of + chatter note; amber "Duplicate" badge in LeadDetail header (links to original) + "Dup" tag in Leads list.
- **Case 22 Attachment eye/view**: eye icon opens an inline preview modal (image/PDF) with close; blob URL revoked on close.
- **Case 23 WhatsApp per-message status**: wa webhook now parses `statuses[]` → updates wa_messages.status/status_at/error + status_history; UI shows Queued/Sent/Delivered/Read/Failed/Received badges per message (outbound w/o status → "Sent").
- **Case 24 Agent status time tracking**: backend already locks start+end+duration on each /agent/status change; added "Show all statuses (full timeline)" toggle in Break Reports (breaks_only=false).
- **Case 21 WhatsApp not working**: PENDING clarification from user — most likely the live-send block (WABA #200 permissions + no phone_number_id). Awaiting exact symptom.


- Root cause of user's "saving but not connecting / no leads": NOT a CRM bug (backend 7/7, frontend 100%). Webhook verify (GET challenge), HMAC-SHA256 signature check, leadgen fetch, and lead mapping all work correctly. Issue is Meta-side: Page not subscribed to `leadgen`, app not in Live mode / no Advanced access to leads_retrieval, or webhook callback URL/verify token mismatch in Meta App Dashboard.
- Added `GET /api/admin/facebook/diagnose` + **"Check connection"** button (Admin → Facebook, `fb-diagnose-button` / `fb-diagnose-result`): live-checks token validity, token↔page match, and whether the Page is actually subscribed to leadgen, returning a specific `next_step`. This is the tool to pinpoint the real problem on production.
- Known minor (not fixed): PATCH /api/admin/settings uses $set only (can't unset keys); Field Mapping dropdown shows blank for legacy 'name' target (canonical is 'contact_name'). Neither blocks FB leads when configured via the UI dropdowns.


- Templates → Email editor now has a labeled **"Email HTML body"** textarea (accepts full HTML: tags, inline styles, links, tables) and a **Live Preview** with a **Rendered / HTML source** toggle. Rendered mode renders the HTML design via dangerouslySetInnerHTML with {{1}}/{{2}}/{{3}} → sample values; source mode shows raw HTML. Email sends already use html=True so HTML delivers correctly.
- testing_agent iteration_10: frontend 100% (41/41). WhatsApp template regression clean (plain-text preview, wa_template_name+lang inputs). Defensive note: templates are admin/manager-authored only; DOMPurify sanitization could be added later if non-admins ever get edit rights.
- Note: "Ozonetel not configured" tooltip on the lead Call button in PREVIEW is expected (telephony API key/campaign not seeded in preview DB); production has it configured.


- Comprehensive test across Cases 1-17: backend 27/27 pytest pass, frontend 100%. No functional bugs found. Suite saved at `/app/backend/tests/test_iter9_full_regression.py`.
- Verified: Case1/3 automations (multi-action, on_stage_set/on_tag_set), Case2 custom fields render+save in lead form, Case4 Facebook test-lead, Case5 click-to-dial (`click-to-dial-button`) + Calls tab recordings, Case6 multi-device auth + Bearer token, Case7 Excel/PDF export, Case9/10 webhook intake + setup guide, Case11 attachments lifecycle, Case12/13 Manage Users, Case14 Marketing, Case15 "New / Unassigned", Case16/17 template editor+preview.
- Polish added this batch: `DELETE /api/users/{id}` (admin-only; blocks self/last-admin/users-with-active-leads) + Delete button in Manage Users (`delete-user-{id}`). Cleaned up leftover test users (1002-1004).
- Still MOCKED/QUEUED pending user action: WhatsApp live send (WABA #200 perms + no phone_number_id) and Gmail email (OAuth not yet connected) — both QUEUE, not bugs.


- Integrated **Gmail API send via Google OAuth 2.0** (`core/gmail_send.py`, `routes/gmail.py`): auth-url → consent → callback stores refresh token in `settings.key=gmail`; auto-refreshes access token; sends MIME email via `users.messages.send`. Endpoints: `/api/admin/gmail/auth-url`, `/api/oauth/gmail/callback`, `/api/admin/gmail/status`, `/api/admin/gmail/disconnect`, `/api/admin/gmail/send-test`.
- Wired live send: lead `send_email` and marketing **email** campaigns now send live via Gmail when connected (subject/body with {{1}}→lead name), else QUEUE.
- New **Admin → Email** tab: Connect Google account, shows required redirect URI to register, status (connected email), test-send, disconnect. Query-param toast on `?gmail=connected`.
- Creds in backend/.env: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GMAIL_REDIRECT_URI (preview). Verified: auth-url generates valid Google consent URL; status endpoint works; UI renders.
- ⚠️ ACTION REQUIRED by user to go live: in Google Cloud Console add redirect URI `https://homeivf-crm-preview.preview.emergentagent.com/api/oauth/gmail/callback` (and the production one after deploy), enable Gmail API, add gmail.send scope, add account as test user if app in Testing, then click Connect. The previously-registered `homeivf.com/google_account/authentication` URI does NOT work for the CRM. Live send unverified until connected.


- Added `POST /api/admin/whatsapp/sync-odoo-templates` (admin): pulls Odoo `whatsapp.template` records (`template_name`, `lang_code`, `status`, `template_type`) and links them onto CRM `templates_whatsapp` by name → sets `wa_template_name` + `lang` + `status`. Ran it: **54/54 approved templates linked** (e.g. "Appointment Booking 2" → `appointment_booking_2`). UI button: Admin → WhatsApp → "Sync approved templates from Odoo".
- Template editor now shows the approved Meta name pre-filled + live preview.
- ⚠️ Multi-variable templates (e.g. appointment_booking_3 uses {{1}}..{{5}}) — `send_lead_template` currently only auto-fills {{1}} (lead name). Live multi-variable sending will need per-variable→lead-field mapping. Live WA send still blocked on WABA `30291513857161871` permissions (#200) + Phone Number ID.


- **Case 7 — Exports** (`routes/export.py`): `GET /api/export/leads.xlsx` (date range + all lead filters, styled openpyxl, role-scoped) and `GET /api/export/report.pdf` (reportlab summary: totals, conversion rate, by stage/source/agent). UI: Reports page **Export bar** with date pickers + Excel/PDF buttons.
- **Case 11 — Lead attachments** (`routes/attachments.py` + `core/storage.py`): multiple files per lead (medical reports etc.) via Emergent object storage; upload/list/download(soft-auth via cookie/?auth=/Bearer)/soft-delete. UI: **Attachments tab** on LeadDetail with drag-drop dropzone (25MB cap), download & delete.
- **Case 14 — Marketing** (`routes/marketing.py`): campaigns CRUD + `/audience-count` + `/send`. Audience = lead filters (stage/source/tag/city/state). WhatsApp sends live via Cloud API when configured else QUEUES; email always QUEUES (no provider yet). New **/marketing** page + nav (Megaphone).
- **Case 5 — Calls tab** on LeadDetail now shows recording `<audio>` player + duration + disposition (click-to-dial already existed).
- **Case 16/17 — Template editor**: live preview pane (renders {{1}}→sample name); WhatsApp templates gained `wa_template_name` + `lang` fields (used by live Cloud send).
- **Case 15 — "Undefined" lead stage** relabeled to **"New / Unassigned"** in dashboard funnel, trends, and pivot.
- **Case 6 — Robust auth**: Bearer-token fallback — login stores JWT in localStorage (`hivf_token`), axios attaches it as Authorization header so auth survives browsers that block cross-site cookies (Safari ITP / mobile in-app browsers / strict 3p-cookie). Cookie path unchanged.
- **WhatsApp token**: user-provided System User token stored (valid/decrypts) but WABA `30291513857161871` returns Meta (#200) permission errors → needs `whatsapp_business_management`+`whatsapp_business_messaging` perms + System User assigned to WABA + a Phone Number ID. Until then WA marketing/template sends QUEUE.
- **Already complete from prior batches (verified)**: Case 1 & 3 (automation triggers on tag/stage + WA/email/assign/tag actions), Case 2 (drag-drop custom-field builder + typed rendering in lead form), Case 4 (Facebook Page field-mapping + test), Case 9/10 (webhook capture + new setup guide & sample HTML form in Admin→Webhooks), Case 12/13 (Manage Users: create/role/activate/reset-pwd).
- **STILL NEEDS USER INPUT**: email provider for live email (Resend/SendGrid/SMTP) — currently queued; WhatsApp WABA permissions + Phone Number ID for live WA.


- **§6 Agent Productivity & Call Analytics** (`routes/agent.py` GET `/api/agent/analytics?date=`): role-aware daily per-agent metrics from call_events grouped by created_at_ist day — total, connected, missed, outbound, incoming, avg_duration, talk_time, conversions (disposition=Converted), break_seconds (status_logs), connect_rate. Returns {date, is_manager, agents[], totals{}}. Managers/admins see full active-agent roster (zero-activity rows hidden); callers see only their own row.
- **Call Center page** (`CallCenter.jsx`): new tabs — **Agent Analytics** (admin/manager, 6 summary cards + per-agent leaderboard table w/ trophy on top row + date picker), **My Stats** (callers — own analytics), **Pending Queue** (all roles — queued outbound calls awaiting dial via `/api/calls?status=queued`). Manager-only tabs (Agent Analytics, Agent Live Status, Break Reports) hidden from callers.
- **Dedicated test Agent login** created for agent-level functionality testing: agent@homeivf.com / Agent@2026 (role=caller, id 1001). Sample call_events + break status_logs seeded for today (preview only) so dashboards are demonstrable.
- Login bug ("can't login from interface") was NOT reproducible on preview — backend curl + UI login both succeed (200, cookies set). Concluded production-only / stale-deploy; awaiting user confirmation.


## Implemented (2026-06-24, batch 9) — Ozonetel Auto-Dialer Phase 2 (call-center) — 21/21 tests + 6/6 frontend e2e (iteration_6)
- **§5 Agent break/status system** (`routes/agent.py`): statuses Available / On Call / Lunch Break / Washroom Break / Refreshment Break / Meeting / Offline. POST/GET `/api/agent/status`, `/api/agent/me`; `status_logs` collection tracks every status span with durations; break time = time in break statuses. Header **AgentStatusSwitcher** (all roles) persists status.
- **§4 In-call disposition popup**: IncomingCallBanner now logs an outcome — Interested / Not interested / Call back later (+ follow-up datetime) / Converted (+ notes). `POST /api/calls/{id}/disposition` updates the call, tags the lead with the disposition, sets stage "Converted" on Converted, sets follow_up_date on Call back later, and logs to chatter.
- **§7 Call Center page** (`/call-center`, nav added): tabs Call Logs (with recording audio player + disposition), Missed Calls (status=missed), Agent Live Status (admin/manager — live agent grid w/ status + break-today, auto-refresh), Break Reports (admin/manager — per-date break log table). `GET /api/calls` gained a `status` filter; `GET /api/agent/live` & `/api/agent/status-logs`.
- All QA/test artifacts purged. Removed a test that hit the live dialer once campaign was configured.
- **Still TODO (Phase 3 of brief)**: §6 Agent productivity & call analytics dashboard (daily per-agent calls/connected/missed/avg duration/talk time/break time/conversion), and a Pending Queue view (leads pushed to dialer awaiting dial).

## Implemented (2026-06-24, batch 8) — Ozonetel Auto-Dialer Phase 1 (per "Auto Dialer Logic Brief") — 20/20 calls+changes tests pass
Campaign confirmed: **Autocallback_homeivf** (Progressive, Nonagentwise, DID 919262104390) → Ozonetel's own dialer handles FCFS + agent assignment; the CRM feeds leads + records outcomes.
- **§3 Autodialer feed**: `POST /api/calls/push-to-dialer` {lead_ids[]} → AddCampaignData to the campaign (checkDuplicate=true, no agentId since Nonagentwise). Leads page → select leads → **"Push to Dialer"** button (bulk bar). Click-to-dial ("Call" on a lead) now works too (campaign_name set).
- **§1/§2 CDR callback**: `POST /api/calls/ozonetel/cdr` (Ozonetel form-encoded `data` JSON) → enriches the screen-pop call_event (status/duration/TalkTime/recording AudioFile/disposition) by ucid, or creates one; **auto-creates a lead** if the number is new — source "Ozonetel Incoming Call" (answered) / "Ozonetel Missed Call" (NotAnswered, tagged "Missed Call") / "Ozonetel Outbound Call"; logs to chatter with recording link. Lead creation happens at CDR (has duration+recording), NOT on the ring (avoids spam-lead creation).
- catalog `_ensure_catalog` get-or-creates source/tag with max-id+1 (migrated catalogs bypassed the counter).
- campaign_name="Autocallback_homeivf", dial_did="919262104390" seeded in preview settings.
- **Production URLs** (live after redeploy): Screen-Pop (frontend) `https://crm.homeivfmarketing.com/screen-pop?phoneNumber={phoneNumber}&ucid={ucid}&callerID={callerID}&did={did}&agentID={agentID}&phoneName={phoneName}` ; CDR callback (backend) `https://crm.homeivfmarketing.com/api/calls/ozonetel/cdr`.
- **STILL TODO (Phase 2/3 of brief)**: agent status/break system (§5) + Agent Live Status, enhanced agent popup with disposition buttons & notes (§4), agent productivity & call analytics (§6), dedicated tabs (Pending Queue, Call Logs, Missed Calls, Agent Analytics, Break Reports) (§7).

## Bug fix (2026-06-22) — Production "logs in then instantly logs out"
- Root cause: production frontend is served from custom domain https://crm.homeivfmarketing.com but its bundle calls the backend at https://hi-connect-1687.emergent.host (cross-site). Auth cookies were `SameSite=lax`, so the browser set them on login but refused to send them on the background `auth/me`/`refresh` XHR → 401 → redirect to /login (instant logout). Backend auth itself was fine (curl login + auth/me → 200 on both envs).
- Fix: `core/security.set_auth_cookies` now issues cookies with `SameSite=None; Secure` (was lax) so they ride cross-site XHR. CORS already reflects the origin with credentials. Verified on preview: login → auth/me → refresh all 200 with SameSite=None. REQUIRES REDEPLOY to take effect on production.

## Implemented (2026-06-17, batch 7) — Live WhatsApp Cloud API + Facebook app creds — 17/17 + 8/8 backend tests pass
- **WhatsApp Business Cloud API** (`core/whatsapp_cloud.py`, `routes/wa_cloud.py`): live template + session-text sending wired into per-lead WhatsApp send (leads.py), automation `send_whatsapp_template` action (utils.py), and free-text WhatsApp thread (whatsapp.py). Inbound webhook GET/POST `/api/webhooks/whatsapp` (verify handshake + X-Hub-Signature-256 + mirrors to wa thread + logs to matching lead chatter). Admin endpoints: status, phone-numbers, templates, send-test. Admin → WhatsApp tab (config form w/ masked secrets, copy-able callback URL, fetch phone numbers/templates, "Use" to set phone_number_id, send test). Live send gated on access_token+phone_number_id; otherwise safely queues (pending_api_credentials) — no behavior change for unconnected state.
- **Facebook** Admin tab now pre-seeded with user's App ID + App Secret. Lead Ads still needs Page ID + Page Access Token to go live.
- **BLOCKER (user action)**: WhatsApp System User token provided failed Meta validation (OAuth 190 — truncated in paste). Need a clean token + Phone Number ID; and the Facebook Page ID + Page Access Token. Then redeploy.

## Implemented (2026-06-17, batch 6) — Odoo-parity "changes & issues" doc — 14/14 backend tests + 100% frontend e2e (iteration_5)
Production: https://crm.homeivfmarketing.com (built in preview; redeploy to push). Autodialer ON HOLD per user.
- **Case 1/3 — Automations like Odoo (multi-action)**: a rule now runs MULTIPLE actions in order (Admin → Automations → New rule → "+ Add another action"). Action types: Send WhatsApp template, Send Email template, Add tag, Set lead stage, Assign to user. Engine already iterated the actions list; UI now builds it. Per-row testids automation-rule-<id> / automation-delete-<id>.
- **Case 2 — Odoo-Studio drag-drop Form Builder** (`Admin → Custom Fields`): components palette (9 field types: Text, Multiline, Integer, Decimal, Monetary, Date, Date&Time, Checkbox, Dropdown) → drag onto (or click to add into) the "Meta/Google Q&A" or "Custom Fields" section dropzones; drag field cards to reorder (persisted via `sequence` + POST /catalogs/custom-fields/reorder); hard-delete affordance on disabled fields. Lead detail (FieldEditor/fieldDisplay) renders the correct typed input (date/number/checkbox/textarea/select) and value formatting (₹ for monetary, Yes/No for checkbox). `custom_fields` gained `sequence`; create validates field_type; DELETE supports `?hard=true`.
- **Case 4 — Facebook Lead Ads → CRM** (`routes/facebook.py`, ready-to-connect): public GET `/api/webhooks/facebook` (Meta verify handshake), public POST `/api/webhooks/facebook` (validates X-Hub-Signature-256 with App Secret, fetches each lead via Graph API v25.0 + Page Access Token, maps fields → CRM lead, round-robin assigns, fires on_create automations). Admin endpoints: `/admin/facebook/test` (simulate a lead to verify mapping without Meta), `/admin/facebook/subscribe` (subscribe Page to leadgen), `/admin/facebook/status`. Admin → Facebook tab: config form (App ID/Secret/Page ID/Page Token/Verify Token/Graph version — secrets masked), copy-able callback URL, field-mapping editor (FB field → CRM field incl. custom fields), "Send test lead". Config in DB settings key="facebook" (no secrets in source). Unmapped FB answers land in the lead's Q&A card as x_custom_*.
- New tests: tests/test_changes.py (6). All QA artifacts purged; real migrated chatter untouched.
- **User action to go live (Case 4)**: in Admin → Facebook enter your Meta App ID/Secret, Page ID, Page Access Token (perms: leads_retrieval, pages_manage_metadata) + a Verify Token, Save, then in Meta App → Webhooks subscribe the page to `leadgen` using the shown callback URL + verify token (or click "Subscribe Page to leadgen"). Live delivery needs the Meta app reviewed/approved.

## Implemented (2026-06-15, batch 5) — TifTech rebrand + Ozonetel telephony (incoming-call screen-pop) — 8/8 calls tests + 100% frontend e2e (iteration_4)
- **Rebrand**: "Powered by TagQuest" → "Powered by TifTech" everywhere (Login, sidebar, index.html title/meta/og, /api/health). No "TagQuest" string remains.
- **Ozonetel incoming-call integration** (`backend/routes/calls.py`):
  - PUBLIC `GET/POST /api/calls/ozonetel/screenpop` — Ozonetel hits this on each incoming call (params: phoneNumber, ucid, callerID, did, agentID, phoneName, type, campaignID...). Matches caller→lead by phone_digits, matches agent→CRM user (ozonetel_agent_id / ozonetel_phone_name), records call_events, logs "📞 Incoming call … (via Ozonetel)" to lead chatter. Idempotent per ucid.
  - `GET /api/calls/active` (auth) — live incoming call for the logged-in agent (last 45s, matched by mapping/user_id) → powers the floating IncomingCallBanner (polls every 5s, mounted in Layout).
  - `GET /api/calls` (paginated, caller-scoped), `GET /api/calls/lead/{id}` — call history (shown in lead-detail "Calls" tab).
  - `POST /api/calls/dial` (auth) — click-to-dial via Ozonetel AddCampaignData API (https://{domain}/ca_apis/AddCampaignData); guarded → HTTP 400 with clear message until an outbound campaign is configured.
- **Agent mapping**: users gained ozonetel_agent_id / ozonetel_phone_name (users.py UserUpdate); editable in Admin → Telephony.
- **Frontend**: ScreenPop.jsx (PUBLIC route /screen-pop for Ozonetel iframe — matched lead card / no-match / open-in-CRM), IncomingCallBanner.jsx, Admin → Telephony tab (config form, copy-able Screen-Pop URL, agent-mapping table, recent-calls table; API key field masked), LeadDetail Call button + Calls tab.
- **Config** stored in DB settings key="ozonetel" (domain in1-ccaas-api.ozonetel.com, username homeivf, api_key, campaign). Pre-seeded with user's real key/username (campaign blank — user to fill for click-to-dial). NOT hardcoded in source.
- Data hygiene: all QA/test call_events + chatter purged; real migrated Odoo "Incoming call" chatter preserved. New suite: tests/test_calls.py (8 tests).
- Screen-Pop URL to paste in Ozonetel (Admin → Settings → Screen Pop URL): `https://<crm-domain>/screen-pop?phoneNumber={phoneNumber}&ucid={ucid}&callerID={callerID}&did={did}&agentID={agentID}&phoneName={phoneName}`

## Implemented (2026-06-11) — Phase 1 COMPLETE & TESTED (32/32 backend tests, all frontend flows pass)
- JWT auth (cookies + bearer), brute-force lockout, admin seed, change-password
- User management (roles, activate/deactivate, password reset)
- Leads: list (filters: search/stage/tags/caller/source/follow_up/active/dates; sort; pagination on 99.5K), group_counts (Odoo-style group-by incl. tags unwind + day/month), kanban by lead_stage, detail, create, PATCH w/ change-tracking to chatter, lost/restore, bulk (assign/tags/stage/archive/follow_up)
- Chatter: migrated history + notes/logs, activities (schedule/done/cancel, my-queue)
- Follow-ups page (overdue/today/upcoming)
- WhatsApp inbox: 10,936 migrated conversations + threads; sends queue (pending API creds)
- Reports: pivot engine (rows×sub-rows×cols, label resolution, totals) + 8 presets + dashboard (KPIs, 14-day chart, funnel, leaderboard, top dispositions)
- Templates: WA (55) + Email (32) migrated, full CRUD
- Webhooks: public lead-capture endpoints w/ field aliasing, round-robin auto-assign, hit counter
- Automations: on_create/on_tag_set/on_stage_set → send template (queued)/add tag/set stage/assign
- Admin panel: Users/Tags/Dropdowns/Webhooks/Automations/Assignment/Migration tabs
- Saved filters (per-user, shareable)
- Full migration: catalogs, 27 users, templates, 99,516 leads, 16 activities, 10,936 WA channels, ~38.7K WA messages, ~910K lead messages, 96K contacts (background, resumable)
- HomeIVF branding (scraped logo, soft blue/violet, Nunito/Figtree), "Powered by TagQuest", data-testids everywhere

## Implemented (2026-06-11, batch 2) — Drill-downs, Sorting, Audit, Visual Analytics (50/50 tests pass, iteration_2)
- Pivot reports: raw keys returned → EVERY cell/row/child clickable, drills to /leads with combined filters; column-header sorting; FULL filter bar (date/status/caller/tag/stage/source/FU tag/ads platform/campaign/state/city)
- Dashboard fully clickable: KPIs, funnel rows, leaderboard rows, top tags, chart bars → filtered leads
- Leads table: sortable column headers (whitelisted sort fields), FU Tag filter, more filter chips (campaign/ads/state/city/lost_reason)
- Follow-ups: whole row clickable → lead detail; Quick Note modal (note + reschedule + disposition tag) without leaving page
- Migration Audit tool (Admin > Migration): live XML-RPC count comparison Odoo vs CRM per entity with ✓/✗ + explanatory notes; persisted to settings.last_audit. Notes: Odoo keeps growing while team still uses it → rerun migration script (resumable, upserts) to sync deltas before cutover
- Visual Analytics (Reports tab): stacked-area lead volume trend (day/week/month), conversions + conversion-rate dual-axis line, source donut (clickable), DOW×Hour incoming heatmap (90d IST), Caller×Day load heatmap (clickable cells) — recharts + custom CSS heatmap grids
- All Emergent branding removed; title/meta = "HomeIVF CRM | Powered by TagQuest", HomeIVF logo favicon
- Data-completeness facts (verified): all 10,936 WA channels have clean 10-digit phones; 99,532 leads have chatter; Odoo only stores OPEN activities (16) — done activities live in chatter (faithful migration)

## Implemented (2026-06-11, batch 3) — Odoo Delta Sync + Production Audit (54/54 tests pass)
- **Odoo Sync** (Admin > Migration): last-record timestamps (lead activity, chatter — IST), last sync run, full reconciliation counts; "Sync Now" → confirm modal stating exact window ("from X UTC → now") + rules (Odoo wins on conflicts, CRM-created leads untouched); background sync via migration/odoo_sync.py (subprocess, tracked in sync_runs, polled live in UI); completion shows per-entity new/updated + new totals; settings.last_sync persisted. Empty DB → auto FULL import mode (production bootstrap).
- Live-verified delta sync: +93 leads, 95 updated, +454 chatter, +8 WA chats, +46 WA msgs, +68 contacts in 14s; post-sync audit = ALL ENTITIES MATCH (99,609 = 99,609 leads; 910,638 = 910,638 chatter).
- Sync semantics: leads by write_date>=since (15-min overlap buffer); messages/wa_messages/contacts by id>checkpoint; users & templates INSERT-ONLY (CRM-side role/password/template edits preserved); catalogs upsert; open activities upsert.
- **Production audit**: zero hardcoded URLs/dummy/mock/demo code (grep-verified); all config via env fail-fast; only intentional queue behaviors (WhatsApp/email sends pending API creds, clearly labeled); e2e flows (create lead, notes, activities, follow-ups, quick notes, bulk, webhook intake) covered by 54-test suite. Refactor: odoo_migrate.py now exposes get_lead_fields() + transform_lead() shared with sync.
- New endpoints: GET /api/admin/sync/status, POST /api/admin/sync/start (admin-only, 409 if already running, stale-run recovery), GET /api/admin/sync/runs(+/{id}). New tests: tests/test_sync.py.
- ⚠️ DEPLOYMENT NOTE: production (hi-connect-1687.emergent.host) has its OWN empty database — after redeploying these features, click "Sync Now" there once: it auto-detects empty DB and runs the full import into production.

## Implemented (2026-06-12, batch 4) — "CRM Testing Points" PDF: ALL 8 CASES COMPLETE & TESTED (iteration_3: 25/25 case tests pass)
- Case 1: Address (street) + City + State dropdown (36 states) + Country dropdown (19) on lead Contact card — editable, persisted
- Case 2: "New tag" button + popup on lead detail; any user can create disposition tags (matches Odoo); tag auto-added to lead + global catalog
- Case 3: "Meta / Google Q&A" card on lead detail — landing-page/ads questionnaire answers shown separately with heading, editable, for agent confirmation on calls
- Case 4: Custom Fields builder (Admin > Custom Fields tab) — like Odoo Studio: label, text/dropdown type, section (Q&A card or Custom Fields card), webhook/ads aliases for auto-capture from landing pages & Google/Meta lead forms; fields instantly render + editable on every lead; webhook intake maps aliases → lead.custom
- Case 5: WhatsApp template popup on lead (55 templates, search + preview + phone override) → queues to outbound_queue + chatter log (live send once Meta API connected)
- Case 6: Compose Email modal on lead (To/Subject/HTML body, 32 templates, save-as-template) → queues + chatter log (live once SMTP connected)
- Case 7: UTM Source / UTM Medium / UTM Campaign dropdowns on Attribution card (catalogs utm_*, managed in Admin > Dropdowns)
- Case 8: Automation triggers (Admin > Automations): when tag added / lead stage changes / lead created → send WhatsApp template, send email template, add tag, set stage, assign. FIXED bug: on_stage_set now fires on lead_stage change (UI stepper), not only stage_id; bulk add_tags/set_stage/set_lead_stage now fire automations per lead
- Bug fixes: catalogs.py route-ordering (custom-fields PATCH/DELETE 404 — specific routes now before generic /{ctype}/{cid}); reports.py trends + caller_day heatmap 500s (KeyError on missing $group _id keys → .get())
- All TEST_* artifacts purged from DB (50 leads, 22 tags, 13 fields, 10 webhooks)
- New test suite: tests/test_crm_8_cases.py (25 tests)

## Backlog
### P0 (Phase 1.5 — needs user API credentials)
- Meta WhatsApp Business API live send/receive (process outbound_queue, webhook for inbound)
- MyOperator auto-caller/OBD integration + call logging
- SMTP/Gmail outgoing email (welcome emails, templates)
### P1 (Phase 2 — AI, user-approved Emergent LLM key)
- AI insights/recommendations panels per section (lead scoring, next-best-action, caller coaching)
- AI Brain: conversational analytics chat over CRM data (sessions, multi-turn)
### Cutover plan (user-confirmed 2026-06-12)
- NO scheduled auto-sync needed. One final incremental "Sync Now" just before switching off Odoo, then run standalone.
### P2
- Custom lead form builder (hosted forms posting to webhooks)
- Duplicate field cleanup (user deferred), lead dedupe/merge by phone
- CSV export, rate-limiting on public webhook, contacts page UI
- Production deploy to homeivfcrm.com

## Key Endpoints
/api/auth/*, /api/users, /api/leads (+/group_counts, /{id}, /bulk, /{id}/lost|restore|messages|activities), /api/activities, /api/catalogs/{type}, /api/templates/{whatsapp|email}, /api/whatsapp/channels (+messages, send), /api/whatsapp/lead/{id}, /api/reports/{pivot|dashboard}, /api/webhook/lead/{token} (public), /api/webhooks, /api/filters, /api/admin/{migration/status|settings|automations|outbound_queue}

## Test Assets
- /app/backend/tests/test_homeivf_api.py (32-test regression suite, run: cd /app/backend && python -m pytest tests/ -q)
- /app/memory/test_credentials.md, /app/auth_testing.md, /app/test_reports/iteration_1.json
- Odoo discovery dumps: /app/discovery/out/*.json
