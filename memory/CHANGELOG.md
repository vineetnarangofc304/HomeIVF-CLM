# HomeIVF CRM — CHANGELOG

(Newest first. PRD.md holds the static problem statement / architecture; this file grows over time.)

## 2026-06 — DEPLOYMENT FAILURE fixed: /health 404 + startup crash-risk + .gitignore + OAuth redirect — deployment_agent PASS

- **Reported:** Emergent K8s deploy failing. Logs showed `GET /health → 404` (repeated from 127.0.0.1 = the
  kubelet probe) plus Atlas `ReplicaSetNoPrimary` / `SSL handshake timed out` (no primary) causing 180s
  ServerSelection/WaitQueue timeouts on every endpoint.
- **Root causes (code-fixable):**
  1. App only exposed `/api/health`; the platform probes `/health` at the container root → 404 → pod never
     Ready → deploy fails.
  2. `@app.on_event("startup")` ran ALL admin/catalog seeding as un-guarded `await` DB calls → if Atlas is
     unreachable at boot (it currently is), the startup event raises → uvicorn aborts → container crash-loops
     → deploy fails.
- **Fixes (code only, no Docker changes):**
  - `server.py`: added root `@app.get("/health")` → `{"status":"ok"}` with NO DB access (verified 200 on the
    container port). Moved seeding into background task `_seed_defaults_safe()` (retries transient DB errors,
    never raises) so the app binds + serves /health instantly and seeding self-heals when the DB returns.
  - `.gitignore`: removed `.env` / `.env.*` / `*.env` (Emergent requires .env committed for deploy).
  - `Admin.jsx`: Gmail OAuth redirect origin now `window.location.origin` (was `REACT_APP_BACKEND_URL`) so it
    works across preview/prod/custom-domain — backend `routes/gmail.py` builds redirect_uri from the passed origin.
- **The Atlas "no primary / SSL handshake" errors themselves are INFRA** (cluster health), not code — the app
  already maps transient PyMongo errors to graceful 503s via the global exception handler.
- **Verified:** deployment_agent = **PASS, 0 blockers**; root /health 200; backend + frontend RUNNING; frontend
  compiles. Ready to redeploy.


## 2026-06-XX — P0 COMPLETE: max_time_ms bound on ALL remaining interactive-pool queries (pool-exhaustion final guard)

- **Why:** recurring prod 504/5xx under load = the interactive Mongo pool getting hogged by slow, UNBOUNDED
  `db.` queries. Hot pollers + the main `/api/leads` list were already bounded (max_time_ms + asyncio wall-clock);
  this closed the remaining gaps so NO single query can stall and exhaust the pool.
- **Bounded this session (reads 5000ms; heavier admin/aggregation 8000–10000ms):**
  - `routes/facebook.py` (had ZERO bounds): `_fb_settings`, `_log_webhook` count/find, `_map_and_create_lead`
    custom_fields + same-day dedup find_one + assignment settings, the Meta webhook `facebook_leadgen_id`
    idempotency find_one (~650×/day path), webhook-log list, recent-leads find+count+users, backfill
    running/status find_ones, and all three `leads.count_documents({facebook_lead:True}, maxTimeMS=8000)`.
  - `routes/whatsapp.py`: set_category channel + leads phone_digits find_one, star/pin/react message +
    channel find_ones, send_message channel + reply find_one, channels_for_lead lead + wa_channels regex find.
  - `routes/leads.py`: lead_audit find, `_track_changes` catalogs/users finds, mark_lost/restore/promote
    find_ones, send_whatsapp template + wa_channels find, bulk-automation `async for db.leads.find(..., max_time_ms=10000)`,
    `_sync_lead_followup` latest find, list_followups, follow-up find_ones, caller-activities list+add,
    followups_analytics `aggregate(pipeline, maxTimeMS=8000)`.
- **Also fixed:** a pre-existing syntax-corruption fragment at EOF of `leads.py` (stray `reminders": out}`)
  left by the previous agent's turn cut-off — it was crashing the backend on reload. Backend now boots clean.
- **Verified:** testing_agent iter84 = backend 100% (34/34) across auth, leads list/detail/update, follow-ups CRUD,
  caller-activity, lost/restore, promote-to-pipeline, send_whatsapp, all Facebook admin endpoints, WhatsApp inbox
  + message actions. No invalid-kwarg 500s. Reusable suite: `backend/tests/test_iter84_max_time_ms_bounded_queries.py`.
- **⚠️ NEEDS PRODUCTION REDEPLOY** to take effect live.


## 2026-06 — PROD OUTAGE (every endpoint 150-256s): missing active_1 recovered + count can't storm

- **Symptom:** at ~10:28 every prod endpoint — even trivial ones (/api/auth/me, /api/agent/me) — took
  150-256s → total DB saturation → "not working for any caller".
- **Root cause (found via /api/version):** prod had only **15** leads indexes; the count-only `{active:1}`
  was MISSING (code expects 16). During the old→new index transition the leads collection briefly exceeded
  MongoDB's hard **64-index cap**, so `create_index(active_1)` failed with "too many indexes" and was never
  retried. Without active_1, `count({active:true})` and `group_counts` COLLSCAN; ×24 callers that scan-storm
  pegged the DB → everything queued for minutes. (Reproduced locally: seeded 64 indexes with active_1 gone.)
- **Fixes (verified iteration_83, 22/22; local 64-cap sim recovered active_1 → 16 indexes, 0 leftovers):**
  1. `server.py _ensure_indexes` now runs the create loop in **2 passes**: create lean set → drop stale
     (frees index slots) → create lean set AGAIN. Any index that failed the 64-cap in pass 1 (active_1) is
     built in pass 2. Guarantees the full lean set on every deploy.
  2. `leads.py _cached_count` uses **estimated_document_count()** for the unfiltered `{active:true}`/empty
     query (instant metadata read, no scan, no index dependency) → the admin/scope=all total can NEVER
     COLLSCAN-storm the DB again. Filtered + caller (own-book) counts stay exact via count_documents on
     selective partial indexes. (Admin unfiltered total is now ~0.02% higher as it includes inactive leads.)
- ⚠️ **Needs a prod REDEPLOY** — the fresh-pod startup runs the 2-pass build and creates active_1 on the live
  DB. After deploying, confirm `https://crm.homeivfmarketing.com/api/version` shows `leads_index_count: 16`.
- ⚠️ **Capacity:** this class of saturation has recurred 15+ times. If prod still saturates AFTER active_1
  is confirmed present, the production MongoDB is under-provisioned for peak load → contact Emergent Support
  to scale the production database (infra, not code).

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
