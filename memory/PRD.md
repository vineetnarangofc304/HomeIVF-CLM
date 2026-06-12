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
