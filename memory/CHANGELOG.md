# HomeIVF CRM — CHANGELOG

(Newest first. PRD.md holds the static problem statement / architecture; this file grows over time.)

## 2026-06 — Code review + deploy health check (pre-redeploy)

- **Deployment health check: PASS** — no hardcoded secrets, envs externalized, /api prefixing + 0.0.0.0:8001
  correct, CORS ok, backend compiles. No blockers.
- **Code review — fixed 1 MEDIUM (robustness):** `_drop_stale_lead_indexes()` did `int(d)` on index
  directions OUTSIDE its try/except, so a legacy non-b-tree `leads` index (text/hashed/geo) would crash the
  cleanup AND skip the one-time backfills (create_dt / name_lc / pipeline). Fixed with `_norm_dir()` (tolerates
  'text'/'hashed'/'2dsphere'), normalization moved inside the per-index try/except, and the drop call wrapped so
  a failure can never block backfills. Proven: a seeded legacy text index is now dropped on startup with no crash.
- **Minor review items fixed:** caller default index → `{user_id, create_dt, id}` (adds the id tiebreaker so a
  caller's list is fully index-covered, no residual blocking sort); corrected the stale `/api/version` doc
  comment (expected count is 16). Leads index count stays 16.
- Verified: iteration_82 regression 22/22 PASS (admin+caller lists, count resolution, sorts/filters/search,
  group_counts, same-day merge, Ozonetel CDR, /api/version=16).

## 2026-06 — Leads-page API audit (answered) + gated the /calls/active poll

- **User asked** why `/api/reports/dashboard?section=kpis` and `/api/leads?follow_up=today` fire on the
  Leads page and how often. **Finding:** they don't — the Leads page only fires 3 one-time requests
  (`/api/leads`, `/api/leads/group_counts`, `/api/filters`). The dashboard/follow-up requests belong to the
  Dashboard/Follow-ups pages; when seen on Leads they are marked `canceled` because `RouteChangeAborter`
  (App.js) aborts the previous route's in-flight GETs on navigation — intended, frees browser connections.
- **Global background pollers (mounted in Layout on every page):** `/api/calls/active` 8s (IncomingCallBanner),
  `/api/whatsapp/unread-summary` 30s (WaNotifier), `/api/leads/followups/reminders` 60s (FollowUpReminder).
  All pause on hidden tab and never overlap (usePoll).
- **Optimization:** `/api/calls/active` is user-scoped to Ozonetel-mapped agents and ALWAYS returns null for
  admins/managers, so polling it for them every 8s was pure waste. Layout.jsx now mounts IncomingCallBanner
  only for `role==='caller' || user.ozonetel_agent_id`. Verified (iteration_81, 100%): admin fires 0
  `/calls/active` over a 14s window; caller still polls.
- **`/api/whatsapp/channels` 504** the user saw = the ingress giving up while the request waited for a DB
  connection from the exhausted pool (same COLLSCAN-storm root cause). The endpoint code is already guarded
  (5s cap → 503); it resolves once the `active_1` DB fix is redeployed.

## 2026-06 — Prod 504 on /api/leads: COLLSCAN-storm root cause + CDR hardening

- **Reported (prod):** a `GET /api/leads` 504 (13s), cascading 503/500s, and `POST /api/calls/ozonetel/cdr`
  requests taking **150-168s**.
- **Root cause:** the earlier 57->15 consolidation dropped the old single-field `{active:1}` index, so the
  unfiltered `count({active:true})` AND the `group_counts` aggregations fell back to full **COLLSCANs**. With
  24 callers each firing a background count + group_counts on every Leads-list load, that COLLSCAN storm
  saturated the MongoDB server — even the Ozonetel CDR webhook's own indexed queries then queued for 150s,
  exhausting the interactive connection pool → `/api/leads` waited >13s for a connection → 504.
- **Fixes (preview, verified 30/30 in iteration_80):**
  1. Re-added a single count-only **`{active:1}`** index → `count({active:true})` = 30ms COUNT_SCAN,
     `group_counts` (lead_stage/user_id/source_lead) = 137ms IXSCAN (were COLLSCANs). Leads index count 15→**16**.
     (The find planner still never picks `{active:1}` for the create_dt-sorted list, so it's not the anti-pattern
     Support flagged — that was 34 active-*leading compound* indexes.)
  2. Raised the non-blocking analytics-pool background-count cap `LIST_COUNT_MS` 8000→20000 so the total
     always resolves (fixes the "-1 forever" total on the loaded prod DB).
  3. Hardened `routes/calls.py ozonetel_cdr`: all its lookups (`_match_lead`, `_match_agent`, settings,
     call_events) now use `max_time_ms=5000` (fail-fast, never hang), and auto-created call leads run their
     automations in the **background** via new `core/utils.schedule_automations()` (fire-and-forget) so the CDR
     webhook returns in ~0.6s and releases its DB connection instead of blocking on a WhatsApp/email send.
- ⚠️ Preview cannot reproduce the prod load, so the load fix is confirmed by code/plan (explain shows IXSCAN
  everywhere) + functional tests; **needs a prod REDEPLOY** to take effect on the live DB.

## 2026-06 — Prod verification follow-up: /api/version marker + Leads total-count fix

- Added a read-only **`GET /api/version`** endpoint (server.py) that reports the LIVE deploy
  signature: `build` tag, `leads_index_count` (+ expected 16), `indexes_consolidated`,
  `list_sort_field:create_dt`, `pipeline_default_filter:removed`, `same_day_merge:true`. Lets any
  deploy be verified at a glance with no login — open `<domain>/api/version`.
- **Verified against production (crm.homeivfmarketing.com) with admin creds, read-only:** login OK;
  leads open in 0.16-0.65s (P0 "server is busy" gone); date-filter 0.37s, lead_stage 0.4s, phone
  search 0.28s; a raw Ozonetel lead (pipeline:false) now appears in the DEFAULT list — a
  new-code-only behavior — so the pipeline-filter removal IS live on prod.
- **Found + fixed a regression the consolidation introduced:** the Leads list TOTAL showed `-1`
  forever on prod. Root cause: dropping the old single-field `{active:1}` index made the unfiltered
  `count({active:true})` fall back to a COLLSCAN of the ~240MB collection; cheap in preview (RAM) but
  it exceeded the 8s background-count cap on the loaded prod DB, so the count silently failed and
  never cached. (The `-1` also *confirms* the consolidation ran on prod — the old count index was
  gone.) Fix: re-added a lone **`{active:1}`** index (count → 32ms COUNT_SCAN; the find planner still
  never picks it, so it's NOT the anti-pattern Support flagged) and raised the non-blocking
  analytics-pool `LIST_COUNT_MS` 8000→20000. Verified in preview: total resolves to 120021.
- Lean leads index set is now **16** (was 15) — the extra is the count-only `{active:1}`.
- ⚠️ Needs ONE more prod REDEPLOY to apply the count fix + expose `/api/version`.

## 2026-06 — P0: MongoDB index consolidation (Emergent Support DB review) + Same-Day Lead Merge

### Root cause of the recurring production crashes (Support diagnosis, confirmed in preview)
The `leads` collection was OVER-INDEXED: **57 indexes**, ~34 of them leading with the boolean
`active`. Because `active` is non-selective, all ~34 looked like candidate plans on every query,
so Mongo spent almost all its time in query PLANNING (not execution) → some `/api/leads` calls
took 60s+ and exhausted the small per-instance connection pool → the "Server is busy" outages.

### What was implemented (Support's 5-point plan, adapted after validating vs. every real query)
1. **Removed the `pipeline:{$ne:false}` filter** from the default Leads list AND from
   `reports.py` dashboard/KPI bases. The `pipeline` field exists on only ~200 docs, so `$ne:false`
   matched ~everything while blocking efficient index use. The "Ozonetel Lead" tab keeps a
   POSITIVE, selective `pipeline:false` match (Support's recommended replacement). Consequence:
   the ~200 raw Ozonetel leads now also appear in the default list, and the Dashboard total now
   equals the Leads "All" count (~120,031) — consistent by design.
2. **Trimmed `maxTimeMS`** on the hot interactive path: `LIST_FIND_MS` 15000→10000,
   `get_lead`/`update_lead` 8000→5000. (Reports stay on the isolated analytics pool + cache.)
3. Dashboard counts already cached (`_dash_cache`) — no change needed.
4. **Consolidated 57 → 15 indexes** in `server.py INDEX_SPECS`: selective field first, `active`
   as a `partialFilterExpression` (not a key), sort field (`create_dt`) last. Added
   `_drop_stale_lead_indexes()` — runs on startup AFTER creating the lean set and drops every
   `leads` index not in the new spec (never `_id_`). Safe metadata op.
5. **Migrated list SORT + date filters from the STRING `create_date`/`create_date_ist` to the
   real-Date `create_dt`** (100% populated in the DB — 0 missing/null). `_parse_day()` builds a
   naive-datetime range matching how `create_dt` is stored (IST wall-clock). Kept `phone_digits`
   indexed. Also **removed the fragile index `hint` logic** from `list_leads` (a hint-by-NAME had
   previously taken the Leads page down on prod); with only 15 indexes the planner picks correctly
   and fast, guarded by the existing wall-clock timeout.

New lean leads index set (15): `id`(uniq), `{create_dt,id}`, `{user_id,create_dt}`*,
`{user_id,lead_stage,create_dt}`*, `{lead_stage,create_dt}`*, `{tags,create_dt}`*,
`{follow_up_date}`, `{pipeline,create_dt}`, `phone_digits`, `name_lc`, `contact_name_lc`,
`email_lc`, `facebook_leadgen_id`(sparse), `{create_date_ist,lead_stage}` (reports).  (* = partial `active:true`)

### Same-Day Lead Merge (was deferred by 3 prior agents)
- New helper `core/utils.check_duplicate_today(phone_digits)` — returns the id of an ACTIVE lead
  with that phone created **TODAY (IST)**, else None (scoped via `create_date_ist` day range).
- **Website webhook** (`webhooks.py`): a same-phone enquiry created the SAME day merges onto that
  lead (returns `merged_same_day:true`, no new lead, logs a "🔁 Repeat web enquiry … merged" note).
  A same phone from a PREVIOUS day is a genuinely new enquiry → new lead (flagged, not merged).
- **Meta/Facebook** (`facebook.py`): `_map_and_create_lead(..., dedupe_today=True)` merges a
  same-day duplicate BEFORE consuming a caller assignment; real webhook logs "merged" vs "created".
  Backfill + test endpoints pass `dedupe_today=False` (always create).

### Verification
- `explain()`: all hot queries use the new `create_dt` indexes, no COLLSCAN/blocking sort (<7ms).
- testing_agent iteration_79.json: **35/35 backend tests PASS, 0 issues**. Leads open fast, all
  sorts/filters/buckets/scopes work, dashboard/KPI/reports OK, same-day merge (same-day merges /
  cross-day creates) confirmed, lead detail + update OK.
- **NOTE:** these fixes are in PREVIEW code. Production (https://hi-connect-1687.emergent.host)
  needs a **REDEPLOY** to apply the index drop/rebuild + query changes.
- A rare UNFILTERED sort on a non-indexed column (e.g. contact_name/city over all 120k) now
  fail-fasts with a clean 504 "please narrow the filters" instead of hanging — by design.
