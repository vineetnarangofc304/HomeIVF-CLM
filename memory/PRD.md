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

## Backlog
### P0 (Phase 1.5 — needs user API credentials)
- Meta WhatsApp Business API live send/receive (process outbound_queue, webhook for inbound)
- MyOperator auto-caller/OBD integration + call logging
- SMTP/Gmail outgoing email (welcome emails, templates)
### P1 (Phase 2 — AI, user-approved Emergent LLM key)
- AI insights/recommendations panels per section (lead scoring, next-best-action, caller coaching)
- AI Brain: conversational analytics chat over CRM data (sessions, multi-turn)
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
