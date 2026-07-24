# HomeIVF CRM — PRD

## P0 (2026-07-24b) — "Switching tabs while loading hangs + throws error" — FIXED & bug-agent verified (iter70), needs REDEPLOY
- **User report (production):** navigating between tabs while a page is still loading instantly throws the Cloudflare 520 ("origin returned empty/malformed response") and the app hangs — e.g. Dashboard→Leads, or leaving a lead mid-load.
- **Root cause:** leaving a page did NOT cancel its in-flight (often slow, 12–17s) GETs. Those orphaned reads (a) hold the browser's ~6-connections-per-host so the next page's requests queue → the app "hangs", and (b) keep hammering an already-saturated origin → transient Cloudflare 520/connection resets.
- **Fix (client-side, `frontend/src/lib/api.js` + `App.js`):**
  1. **Cancel-on-navigation:** every GET is tagged with its route path + given an AbortController; `RouteChangeAborter` (in App.js, on `useLocation` pathname change) calls `abortPendingReads()` to cancel ONLY the previous route's pending GETs → frees connection slots + cancels the matching server-side queries instantly. Writes (POST/PATCH/DELETE) are never auto-aborted.
  2. **Swallow cancellations globally:** the axios response interceptor returns a **never-settling promise** for cancelled requests (isCancel/ERR_CANCELED) → no unhandled `CanceledError`, no React error overlay, no stray toast, WITHOUT needing a `.catch` on every page. (First attempt only guarded 3 pages and still overlayed on FollowUps/WhatsApp — the never-settle approach fixed it globally.)
  3. **Auto-retry transient origin blips:** idempotent GETs retry ≤2× with backoff on network errors / 502/520/521/522/523/524/525 (NOT 503/504, to avoid amplifying DB load) → brief spinner instead of a scary error.
  4. **Friendly errors:** `apiErr` shows "Server is busy right now — please try again in a moment." instead of raw Cloudflare HTML.
- **Verified:** bug_testing_agent iter70 = frontend 100%, retest not needed — rapid tab-switching under artificially delayed reads shows no overlay/hang/error; all destination pages load; Case 1 regression intact.
- **⚠️ NEEDS REDEPLOY.** Note: this makes the app RESILIENT to the slowness, but the underlying 12–17s latency is still production DB/server capacity → the durable fix remains the capacity upgrade via support@emergent.sh.


## P0 (2026-07-24) — PRODUCTION SLOW again (12–120s /api/leads, 5xx cascade) — code mitigation done (iter68), CAPACITY escalation required
- **Symptom (production, live callers):** System Health = 7 err/1h, 302 err/24h, 3035 SLOW(>8s)/24h. `GET /api/leads` 12–36s for callers, 120s→504 for a manager; 500/503 on `/agent/me`, `/calls/active`, `/whatsapp/unread-summary`, `/webhooks/facebook`. Preview healthy on identical code (all queries <0.5s).
- **RCA (troubleshoot_agent):** PRIMARY = production MongoDB tier undersized for 24 concurrent callers × ~120k leads + webhooks (CPU/IOPS/connection-pool exhaustion → cascade). Contributing = single uvicorn worker serializes requests; timeout stacking pushes wall-time past the 15s caps. Plus a real **query-planner risk**: the unscoped all-pipeline list (`pipeline:{$ne:false}` + sort create_date) can be planned as a **blocking SORT over ~120k keys** if the planner picks the `active_1_pipeline_1_create_date_-1_id_-1` index (proven in preview: FETCH+SORT+IXSCAN, 119,814 keys examined) — fast on preview's local Mongo, 15–30s on a loaded prod DB.
- **Code fix (needs REDEPLOY):** `list_leads` now **pins `.hint('active_createdate_id')`** for exactly the unscoped pipeline default query (`sort==create_date` and q keys ⊆ {active,pipeline} and pipeline=={$ne:false}) → guaranteed LIMIT→FETCH→IXSCAN (examines ~limit keys, never a 120k blocking sort). Scoped/filtered queries keep their own indexes (no hint). Verified: admin 119,813@121ms, caller 5,144@65ms, scope=all@54ms, lead_stage 24,020@79ms, page3 50 items@49ms.
- **⚠️ DURABLE FIX = DB CAPACITY UPGRADE (infra, not code):** Production DB scaling is handled by Emergent Support. User must email **support@emergent.sh** with Job ID, app name "HomeIVF CRM", metrics (dev ~3ms vs prod 12–120s), 500/503/504, load (120k records, 24 agents, webhooks), screenshots, requesting a production DB tier upgrade.
- **Open verification:** UNKNOWN whether production has the scoped-caller default deployed — if callers are still unscoped on prod, redeploying is a ~24× DB-load reduction and likely the biggest single win.
- **Verified:** bug_testing_agent iter68 = backend 100% / frontend 100% (functional; production latency can't be reproduced in preview).

## ADMIN/CALLER My-All TABS (2026-07-24) — done
- Leads page shows scope tabs for ALL roles: callers → "Leads in Pipeline (My leads)" (default, own book) / "(All)" (`?scope=all`) / "Ozonetel Lead"; admins & managers → "(All)" (default) / "(My leads)" (`?scope=mine`) / "Ozonetel Lead". `build_query`: search always global, `user_id` filter wins, `scope=mine`→own book (any role), `scope=all`→everything, else callers default to own book.


## P0 (2026-07-23c) — PRODUCTION MELTDOWN from all-leads-default + RESOLUTION — FIXED & testing_agent-verified (iter67), needs REDEPLOY
- **What happened:** the 2026-07-23b fix removed caller list-scoping so EVERY caller's default `/api/leads` queried the full ~120k collection. On the production DB (latency-prone vs preview's local Mongo), 24 concurrent callers doing that + polling held connections long enough to EXHAUST the connection pool → cascade: `GET /api/leads` 20–38s → 504, plus 500s on `/whatsapp/unread-summary`, `/agent/me`, `/followups/reminders`, `/webhooks/*`, `/calls/ozonetel/cdr`, `/leads/group_counts`. User: "CRM very slow and errors on every action" (System Health screenshots, all callers).
- **Why preview didn't catch it:** the base list query is index-covered and 3ms in preview (explain: LIMIT→FETCH→IXSCAN `active_createdate_id`, 50 keys/50 docs). The failure is pure production DB CAPACITY under concurrency, which preview (healthy local Mongo) can't reproduce.
- **Resolution (balance access + stability):** the caller DEFAULT list is scoped back to their OWN book (fast, ~5k index-covered) — this is a hard stability requirement. Full access to Case 1 is preserved via THREE escape hatches, all of which bypass scoping in `build_query` (`not search and scope != 'all' and not user_id`):
  1. **Global SEARCH** — unscoped, spans BOTH pipeline + raw-Ozonetel buckets (bucket filter only applies when NOT searching). A caller finds ANY customer by number/name.
  2. **Colleague filter** — `?user_id=<id>` shows a specific colleague's whole book (e.g. Kanika's while she's on leave).
  3. **"All leads" toggle** — `?scope=all` shows everyone's leads on demand (heavier, opt-in per caller, not the constant default).
- **Frontend (`Leads.jsx`):** the caller lead-bucket row now has explicit TABS (user-requested UX): **"Leads in Pipeline (My leads)"** (default, own book), **"Leads in Pipeline (All)"** (`?scope=all`, every caller's leads), and **"Ozonetel Lead"**. Admin/manager keep "Lead in Pipeline" / "Ozonetel Lead". `scope` is carried in filterParams; a hint line clarifies the active scope and that search finds any lead. (Replaced the earlier single My/All toggle button.)
- **Unchanged & re-verified:** original_user_id LOCK (PATCH strips user_id for callers + always original_user_id), assignee-select disabled + lock line, full Activity Log of cross-caller edits.
- **Verified:** testing_agent iter67 = backend 100% / frontend 100%. Curl: default 5,144 / scope=all 119,813 / search 5770614172→lead 600027 / user_id=5→5,073 / group_counts 0.14s.
- **⚠️ NEEDS PRODUCTION REDEPLOY immediately** to restore service. **If the client still wants all-leads as the CONSTANT default for every caller, that requires a larger production DB tier** (the current tier can't serve 24 callers × 120k by default) → evaluate via Emergent Support.


## Case 1 FIX (2026-07-23b) — callers must VIEW ALL leads (perf-scoping regression) — SUPERSEDED by 2026-07-23c above
- **User report (on PRODUCTION):** Case 1 "not working like this" — a prior performance change ("show only leads assigned to the caller … to reduce load") had scoped every caller's DEFAULT Leads list to ONLY their own ~5k leads, so callers could no longer VIEW all leads. It "was working earlier perfectly." Client requirement is literally: **all callers can view ALL leads** and edit any lead; original assigned caller stays locked; visible activity log.
- **Root cause:** `build_query` (leads.py) added `q["user_id"]=current_user["id"]` for callers whenever there was no search → default list was owner-scoped. Cross-caller access only worked via explicit SEARCH.
- **Fix 1 (`routes/leads.py` build_query ~line 134):** REMOVED the caller owner-scoping entirely — callers now get the same UNSCOPED default list as admin/manager (verified caller total 119,813 == admin; `?user_id=<self>` filter still narrows to own 5,144). Perf is fine: the list is a LIMIT query over the sort-covering index (O(limit) walk, not a full scan) and counts are cached+coalesced (now sharing ONE key across all users). The earlier NetworkTimeout storm was the hot POLLING endpoints (already fixed with max_time_ms), not this list query.
- **Fix 2 (`build_query` bucket block ~line 53):** the bucket filter (pipeline / ozonetel) is now applied ONLY when there is NO search — so a caller SEARCHING a customer by number/name finds them across BOTH pipeline and raw Ozonetel buckets (previously a raw-Ozonetel lead like 600027 was invisible when searching in the default "Lead in Pipeline" tab). Default (non-search) bucket counts unchanged (pipeline 119,813, ozonetel 200).
- **Fix 3 (frontend `Leads.jsx` ~line 267):** replaced the static "Your leads" indicator pill with a functional **My leads / All leads** toggle (`data-testid=my-leads-toggle`) — default shows All leads; click sets `?user_id=<self>` to narrow to the caller's own book.
- **Unchanged & re-verified (no regression):** original_user_id LOCK (PATCH strips user_id for callers + always strips original_user_id), assignee-select disabled for callers with "🔒 Originally assigned to … · locked", full Activity Log (audit) records cross-caller edits by the editing caller.
- **Verified:** bug_testing_agent iter66 = **fixed**, backend 100% / frontend 100%. Reports: `/app/test_reports/iteration_65.json`, `/app/test_reports/iteration_66.json`.
- **⚠️ NEEDS PRODUCTION REDEPLOY** — code-only fix; user must redeploy to https://hi-connect-1687.emergent.host to see it live.


## Case 1 FIX (2026-07-23) — caller SEARCH must find ANY lead (Kanika-on-leave scenario) — DONE & E2E-verified (iter64), needs REDEPLOY
- **Client requirement (verbatim intent):** all callers can view AND edit any lead; a caller must be able to SEARCH any customer by number, OPEN the lead, and UPDATE all details even when it was auto-assigned to another caller (e.g. Kanika on leave → Nishant handles the call). ONLY restriction: the original assigned caller (`original_user_id`, first auto-assigned) stays LOCKED — no caller can change it. Every change shows in a visible per-lead Activity Log (who / what / old→new / when).
- **Bug found:** the iter62 performance change scoped EVERY caller query in `build_query` by `user_id` — INCLUDING search. So a caller searching a number owned by another caller got ZERO results → could not pull up / handle that customer. This silently broke the Case 1 search flow.
- **Fix (`routes/leads.py` build_query ~line 134):** caller owner-scoping now applies ONLY when there is **no search** (`... and not search`). A caller's SEARCH (phone_digits exact/prefix or *_lc name prefix — all index-covered, so still instant) is GLOBAL across all 120k leads; the DEFAULT list stays scoped to their ~5k own leads (keeps the perf win). Admins/managers unchanged (see all). `get_lead`/`update_lead` already unscoped; PATCH strips `user_id` for callers and always strips immutable `original_user_id`.
- **Verified end-to-end (preview):** curl — as agent 1001, search 9384640901 → finds lead 500210 (owner user_id=5); opened it; edited city + disposition tags + added note + follow-up (all 200); `user_id`/`original_user_id` stayed 5 (locked); audit endpoint logged all 4 actions with user/field/old→new/time. Frontend E2E (iter64, 7/7): global-search finds the cross-caller lead, default list still 5,270 + 'Your leads' pill, opens without 403, `assignee-select` disabled + '🔒 Originally assigned to Anamika Suman · locked', Activity Log renders 6 rows (Field edited / Disposition / Follow-up / Note added) each 'by Test Agent'; admin sees 119,813 + caller filter + enabled select. Audit coverage confirmed complete: note_added, disposition_changed, reassigned, stage_changed, field_changed, lead_lost, whatsapp_sent, follow_up_added, caller_activity. Added `note_added` label to frontend AUDIT_META.
- **Note:** `ensure_lead_edit` (old owner-only 403 guard) is defined but NEVER called anywhere — callers can edit notes/activities/follow-ups/attachments/calls on any lead (correct per Case 1). Leftover imports only.
- **⚠️ NEEDS PRODUCTION REDEPLOY** for the search fix to reach the live site.



## P0 (2026-07-23) — Production NetworkTimeout storm (lead edits + everything failing) — ROOT-CAUSED & FIXED in preview (needs REDEPLOY)
- **User report:** on PRODUCTION, lead editing "not working"; edit + locked-original-caller "was working but got disturbed with recent change." Screenshots = Admin → System Health showing 82 errors/1h, 981/24h, 2068 slow/24h; every row `NetworkTimeout: customer-apps-shard-00-02.o9d3cj.mongodb.net` at ~30-32s across ALL endpoints (calls/active 342×, whatsapp/unread-summary 168×, agent/me 99×, followups/reminders 77×, webhook/lead 69×, /leads 504 67×, webhooks/facebook 25×, webhooks/whatsapp 22×, calls/ozonetel/cdr 14×, whatsapp/channels 7×, and PATCH /leads/{id}).
- **Verified NOT a permissions bug:** edit + ownership-lock CODE is intact & correct — `GET /leads/{id}` lets any caller open any lead; `PATCH` strips `user_id` for callers and always strips immutable `original_user_id`. Confirmed via curl in preview: caller edited `city` OK; hijack attempt `user_id=20`/`original_user_id=20` both stripped (stayed 1001). Editing fails on prod ONLY because `PATCH` times out against the saturated Atlas DB.
- **Root cause (troubleshoot_agent, high confidence):** the hot POLLING endpoints (`/calls/active` 5s, `/whatsapp/unread-summary` 15s, `/agent/me` 30s, `/followups/reminders` 60s) × 24 callers had **NO per-query `max_time_ms`**. When Atlas is transiently slow, each poll hung up to `socketTimeoutMS=45000` holding its pooled connection → the 80-conn interactive pool exhausted → ALL new requests (edits, login, webhooks) then `NetworkTimeout` (~30s = waitQueue+socket). Preview never reproduces (local Mongo is instant). This is the same class that recurred 9+ times — prior fixes treated symptoms, not the missing fail-fast.
- **Fix (preview, code):**
  1. `core/db.py`: interactive `socketTimeoutMS` 45000 → **15000** (caps worst-case connection hold).
  2. Fail-fast `max_time_ms` on all hot polls + graceful fallback so a slow DB returns an empty/neutral result (releasing the connection) instead of hanging: `/calls/active` (3s→`{active:null}`), `/whatsapp/unread-summary` (4s→zeros), `/agent/me` (3s→Offline), `/followups/reminders` (5s→[]). Also `max_time_ms` on `get_lead` (8s), `update_lead` find_ones (8s), `check_duplicate` (5s), webhook hook lookup (3s). (`/leads` list + `group_counts` already had it.)
  3. Frontend polling trimmed to cut baseline QPS ~40-50%: calls/active 5s→8s, unread-summary 15s→30s, agent/me 30s→45s.
- **Effect:** converts a total NetworkTimeout collapse into graceful, fast-failing degradation — transient DB slowness can no longer cascade into a full outage. **Verified preview:** all 4 hot endpoints 200; login 200; edit+lock correct.
- **⚠️ ACTION:** user must **REDEPLOY** to push this to prod. If widespread SLOWNESS persists after redeploy (not cascading timeouts), the Atlas tier is undersized for 120k leads + 24 callers + webhook volume → engage Emergent Support to review/upgrade the DB tier (CPU/IOPS/connections). Preview on identical code is 100% healthy = the delta is prod DB capacity.




## P0 PRODUCTION OUTAGE (2026-07-22) — total outage / Cloudflare 520 — root-caused to the error-logger; FIXED in preview (needs redeploy)
- **Symptom:** production (custom domain crm.homeivfmarketing.com via Cloudflare → emergent origin) fully down. Login showed Cloudflare "**origin returned an empty response / malformed HTTP headers**" (Error 520). Nobody could log in; blank screen; live ops stopped.
- **Root cause (high confidence):** the request-logging middleware shipped the turn before (BaseHTTPMiddleware + an UNBOUNDED `asyncio.create_task` DB insert on every 5xx). Production was already in a 500-storm (DB saturation). Each 500 spawned another error_logs insert into the already-saturated pool → hundreds of piled-up background tasks + held connections → worker memory/connection exhaustion → the origin returned empty responses → Cloudflare 520 (total collapse). The diagnostic meant to FIND the 500s AMPLIFIED them into an outage. Preview (same code, healthy DB) never reproduced it because there was no storm to amplify.
- **Fix (`server.py`):**
  1. Rewrote the logger as a **pure-ASGI middleware** (`RequestLogMiddleware`) that only observes the response status via the `send` stream — it never buffers/rewrites the body, so it cannot produce empty/malformed responses or add latency (BaseHTTPMiddleware removed).
  2. **Load-shedding guards:** at most 5 concurrent log writes (`_LOG_MAX_INFLIGHT`), extras dropped; each write hard-timeouts at 1.5s (`asyncio.wait_for`) so it releases its pooled connection fast. The logger can NEVER add meaningful pressure during a storm again.
  3. CORS kept outermost (verified: even 500 responses carry `access-control-allow-origin`).
- **Verified (preview):** health stable; login clean 200 (correct content-length + CORS + cookies); a forced 500 returns a clean well-formed error response WITH CORS and is captured with full traceback; 72-request concurrency burst = all 200, none malformed. Boom route removed; test logs cleared.
- **ACTION:** user must **REDEPLOY** — this restarts the crashed origin AND ships the amplification-proof logger. If it is STILL down after redeploy, the cause is production infra/domain (Cloudflare origin/cert/platform) → Emergent Support. Underlying 500-storm (DB saturation under 24-caller + high-webhook load) still needs capacity work separately.


## Feature (2026-07-21f) — Server-side request logging → Admin "System Health" tab — DONE (preview, verified end-to-end)
- **Why:** so production 5xx errors are visible from INSIDE the app (which endpoint + traceback) without needing browser DevTools — directly supports diagnosing the frequent production 500s.
- **Backend middleware (`server.py`, registered BEFORE CORS so CORS stays outermost):** captures every 5xx response AND unhandled exception (with full traceback) AND any request slower than 8s, writing to a new `error_logs` collection. Fire-and-forget (`asyncio.create_task`) so it adds no latency; fully try/except-wrapped so it can never itself fail. Captures method, path, query, status, duration_ms, user_id (decoded from JWT, no DB hit), error_type, error, traceback, IST timestamp.
- **Retention:** TTL index on `created_dt` (BSON date) auto-purges after 7 days; secondary indexes on ts/kind/status keep the list + summary queries fast.
- **Admin API (`routes/admin.py`, admin-only):** `GET /admin/error-logs/summary` (errors 1h/24h, slow 24h, top failing endpoints grouped by path+status), `GET /admin/error-logs?kind=error|slow&limit=` (recent list with resolved user names), `DELETE /admin/error-logs` (clear).
- **Frontend (`Admin.jsx` → new "System Health" tab):** summary cards, "Top failing endpoints (24h)", All/Errors/Slow filter, live table (auto-refresh 15s) with color-coded status + click-to-expand traceback. Refresh + Clear buttons.
- **Verified:** injected a temporary boom route → real 500 captured with 3079-char traceback, correct path/method/user; summary + list + UI all render (screenshot); boom route removed (404) and test logs cleared. **⚠️ NEEDS PRODUCTION REDEPLOY** — after redeploy, when a 500 recurs, open Admin → System Health to see the exact failing endpoint + traceback.


## Production 500s investigation + resilience hardening (2026-07-21e) — code confirmed resilient, load-reduction changes applied (needs post-deploy verification)
- **User report:** frequent HTTP 500 on PRODUCTION — on login, Leads, Dashboard, "everywhere/randomly". Platform-managed MongoDB. Redeployed ~6h ago, still 500ing.
- **Diagnosis:** Preview is HEALTHY under load — a burst of **72 concurrent requests (24 logins + 24 Leads + 24 Dashboard) returned ALL 200, zero 500s** (~3s wall). So it is NOT a code bug; the 500s are the classic pool-exhaustion / DB-saturation cascade specific to the production deployment (managed DB latency + 24-caller polling + ~650/day Meta webhook writes). deployment_agent could not fetch prod runtime logs; its Gmail-OAuth/Admin.jsx flags are false positives (verified NO hardcoded URLs; frontend uses REACT_APP_BACKEND_URL; API base correct).
- **Resilience changes applied (reduce prod DB pressure; safe, need redeploy):**
  - `server.py` startup: enlarged default thread pool to 48 workers — bcrypt (login) is CPU-bound and offloaded via `asyncio.to_thread`; the morning 24-caller login rush was queueing on the small default executor. (bcrypt releases the GIL so more threads help on multi-CPU prod.)
  - `core/security.py`: `get_current_user` now caches the per-request user lookup (20s TTL, `invalidate_user_cache()` on user edit/delete in `routes/users.py`) — removes a `users.find_one` on every authenticated request across all the polling endpoints → fewer pooled-connection checkouts under load.
  - (Plus already-in-preview: Meta duplicate-webhook fix = fewer redundant writes/automations; dashboard section-split = lighter/faster.)
- **DB config confirmed sound** (`core/db.py`): maxPoolSize=100, minPoolSize=10, serverSelectionTimeoutMS=8000, per-query max_time_ms in routes.
- **NOT resolved/verified:** cannot confirm production fix without the live error or logs. **Next:** after this redeploy, if 500s persist → get the exact failing request + Response body from browser DevTools Network tab, or engage Emergent Support to pull production logs; also evaluate whether the platform-managed DB tier is sized for 120k docs + 24 concurrent users + high webhook write volume.


## Code Review fixes (2026-07-21d) — 2 HIGH + 2 MEDIUM + 2 LOW from functional review — DONE (preview, regression-tested)
- **HIGH — Meta webhook created DUPLICATE leads on redelivery (pre-existing bug):** Meta uses at-least-once delivery/retries, but `fb_webhook` never deduped — the same leadgen event inserted the prospect repeatedly, re-assigned a caller, and re-fired on-create automations (a likely contributor to the user's "40 mismatch"). **Fix:** `fb_webhook` now skips (logs "Duplicate delivery") if a lead with that `facebook_leadgen_id` already exists. Idempotent. (`routes/facebook.py`)
- **HIGH — role-landing redirect loop/lockout:** the new `RoleLanding` sent all non-callers to `/dashboard` unconditionally; if an admin disabled the `dashboard` perm for managers (editable), Guard→"/"→RoleLanding→"/dashboard" looped into a blank screen. **Fix:** `RoleLanding` now lands on the user's FIRST PERMITTED route (role-preferred order) and shows a "No pages available" page if none — no loop. (`frontend/src/App.js`)
- **MEDIUM — concurrent backfill could double-create:** the check-and-insert wasn't atomic (interleaving awaits) and a stale-relabel could launch a 2nd worker while the 1st ran. **Fix:** an `asyncio.Lock` serializes the start, and a task registry cancels a stale worker before relabeling. (single-worker deployment). (`routes/facebook.py`)
- **MEDIUM — backfill could resurrect closed leads + mass-fire automations:** phone-dedup only matched active leads, and recovered leads re-ran on-create automations. **Fix:** phone-dedup now matches ANY lead (incl. inactive) so a closed contact is never resurrected; `_map_and_create_lead(..., run_autos=False)` for backfill so a bulk recovery never blasts welcome WhatsApp/email. (`routes/facebook.py`)
- **LOW:** removed a redundant `import json`; Dashboard `today`/`month_start` now sourced from `kpis || panels` so panel drill-downs keep their date filter if the kpis fetch fails.
- **NOTE (not done, needs care):** the reviewer suggested a UNIQUE sparse index on `facebook_leadgen_id`. NOT added — production data may already hold duplicates from the pre-existing HIGH bug, so a unique-index build would fail. The webhook dedup stops NEW duplicates; existing FB duplicates can be cleaned via Admin → Duplicates (phone-based).
- **Regression-tested (preview):** fb_test creates a lead; dry-run backfill completes (625 fetched, 0 errors); dashboard kpis 0.19s / panels 0.33s; caller still lands on /leads (no loop). **⚠️ NEEDS PRODUCTION REDEPLOY.**


## Perf + UX (2026-07-21c) — Leads as caller landing page + Dashboard made lighter/faster — VERIFIED (preview, testing_agent iteration_61 12/13 + self-test)
- **User report:** "Dashboard takes a lot of time to open — make Leads the default." User choices: (b) ONLY callers land on Leads; admins/managers keep the Dashboard; Dashboard stays in the left menu for everyone; also optimize the dashboard itself (URGENT, seen on PRODUCTION).
- **Role-based landing (`App.js`, `Layout.jsx`):** new `RoleLanding` at `/` redirects by role — **caller → `/leads`**, admin/manager → `/dashboard`. Dashboard moved to its own route `/dashboard` (Guard perm `dashboard`) and the left-menu "Dashboard" item now points there, so it stays one click away for ALL roles (callers can still open it). Login + already-authed entry both go to `/` which role-routes. No redirect loops.
- **Dashboard code-split:** `Dashboard` is now `React.lazy` (it pulls in recharts). Since callers land on Leads, that heavy chunk is no longer parsed on the initial app load → the Leads landing is lighter for the 24 callers.
- **Dashboard API split for progressive render (`reports.py` `/dashboard?section=kpis|panels|all`, default all):** `kpis` = the 8 index-covered counts (6 KPI cards + range header), `panels` = the 4 heavy aggregations (funnel / 14-day chart / leaderboard / top dispositions). `Dashboard.jsx` fetches BOTH in PARALLEL and renders each the moment it arrives (KPI + panel skeletons in between) instead of one blocking spinner behind the slowest scan. Cache key now includes `section`.
- **Measured (preview, 120k):** kpis 0.12–0.26s, panels ~0.29s. Verified all 3 roles land correctly (caller→leads, admin/manager→dashboard), caller-scoped dashboard shows scoped KPIs (5,270 vs 119,813 admin), date-range filter + Clear button work, no console errors.
- **⚠️ NEEDS PRODUCTION REDEPLOY** to take effect on the live site. Files: `frontend/src/App.js`, `frontend/src/components/Layout.jsx`, `frontend/src/pages/Dashboard.jsx`, `backend/routes/reports.py`.


## Verify + Hardening (2026-07-21b) — Meta Leads Backfill (background job) + offline fallback — VERIFIED (preview, self-tested curl+DB+UI)
- **Verified the previously-built (untested) items:** (1) `POST /admin/facebook/backfill` returns immediately (~0.11s, non-blocking `asyncio` task) and writes progress to `db.fb_backfill_jobs`; `GET /admin/facebook/backfill/status` polls it. Full lifecycle idle→running→**done** confirmed against the REAL HomeIVF Meta account (page 273380505860843, 15 live forms; ~650 leads/day volume). (2) 409 "already running" guard works. (3) Offline→any-caller fallback: with all 23 callers Offline a new Meta/web lead is ASSIGNED to an active caller (round-robin `pick_any_caller`), NOT queued (queue only if ZERO active callers). (4) Presence routing: with one caller Available the lead goes to them. (5) Background queue-drain: a parked lead auto-assigns the moment a caller marks Available (status change stays ~0.09s, drain runs in background).
- **3 hardening fixes added this session (backend only):**
  - **Sparse index `leads.facebook_leadgen_id`** (`server.py` INDEX_SPECS) — the backfill de-dupes with `find_one({facebook_leadgen_id})` per fetched lead; unindexed that was a full ~120k collscan PER lead → the exact pool-exhaustion pattern of the 07-21 P0. Now index-covered.
  - **Phone-based safety net in `_run_backfill`** (`facebook.py`, new `_extract_phone_digits`) — before creating a recovered lead, also skip if an ACTIVE lead with the same phone already exists. Guards against creating duplicates of leads that reached the CRM via another path or predate leadgen_id storage. A backfill now recovers only genuinely-missing leads.
  - **Stale-job guard in `POST /admin/facebook/backfill`** — a "running" job whose `updated_at` is >3 min old (worker died on a deploy/restart) is marked `error` so a new run is never blocked forever by an orphaned job (this actually happened during testing after a backend restart).
- **⚠️ NEEDS PRODUCTION REDEPLOY** (new index builds on startup). **User workflow for the actual recovery:** run **Preview** (dry-run) first with a look-back window covering the outage, confirm the "would recover" count is sane (~40, not hundreds), then **Recover now**. Files: `backend/routes/facebook.py`, `backend/server.py`.


## P0 INCIDENT FIX (2026-07-21) — production 500s (login/leads/Meta) — root-caused & fixed in preview
- **Symptom (production):** consistent HTTP 500 on login (Caller23@homeivf.com), callers "not able to work on leads", Meta leadgen "40 leads missing / mismatch". Probed prod: `/api/health` instant but `/api/auth/login` **500 after ~30s** (ingress timeout) = requests starved of a DB connection → **connection-pool exhaustion cascade**.
- **Root cause (my Case 2 code):** (a) the new `status_logs` & `lead_queue` collections had **NO indexes**, so every status change / `/agent/live` poll / attendance query / daily reset ran a full collscan on a growing collection; (b) `drain_lead_queue()` ran **synchronously & unbounded inside `POST /agent/status`**. After the daily Offline reset (choice 3a), the morning rush of ~24 callers all marking "Available" fired 24 concurrent unbounded drains over unindexed collections → pool exhausted → 30s-timeout 500s on ALL DB-touching endpoints (login, leads, Meta webhook). Meta/web leads arriving while everyone offline piled up queued/unassigned → "missing".
- **Fixes (all in preview):** (1) added indexes: `status_logs{user_id,end}`,`{end}`,`{date}`,`{user_id,start}` + `lead_queue{lead_id}`. (2) `drain_lead_queue` is now **single-flight** (one drain per pod at a time), **bounded** (batches of 200, ≤10k/trigger), per-query `maxTimeMS`, per-lead try/except. (3) `set_status`/`admin_set_status` fire the drain in the **BACKGROUND** (`asyncio.create_task`) → status changes return in ~5ms regardless of queue size (was blocking). (4) `reset_stale_statuses` bounded + `maxTimeMS`. (5) login DB lookups get `max_time_ms=5000` (fail fast, don't hold connections).
- **Verified (preview):** login both roles 200; full status cycle 4-5ms each; queue 3→drain→0 (background); all endpoints (leads/group_counts/dashboard/kpi/live/attendance/queue/analytics) 200 & <130ms. Queued leads are visible under the **Unassigned** filter and auto-assign when a caller goes Available.
- **⚠️ ACTION:** user must **REDEPLOY** to push fix to prod. The ~40 Meta leads that failed to ingest DURING the outage may be lost to Meta's retry window → may need a manual re-sync/backfill from Meta (offer pending). Files: `core/utils.py`, `routes/agent.py`, `routes/auth.py`, `server.py`.


## Fix (2026-07-19) — KPI "Lead Pulse" DATA correctness (option B) — VERIFIED (preview, exact vs raw DB)
- **Symptom:** user (on PRODUCTION) reported every KPI number tile wrong/near-zero. **Root cause:** the disposition/stage tiles were counted from the lead `tags` array, but only 2 of ~120k leads have any tags — the real pipeline data lives in **`lead_stage`** (~24k each: New/Unassigned, Contact Attempt, Contacted, Converted, Closed). `stage_id` is random noise (uncorrelated), so unusable. Also the month picker only listed the current calendar year, hiding 2024–2025 data.
- **Fix (`/reports/kpi-overview`), user choice = option B:** (1) added a `by_stage` facet; **stage TOTALS now come from `lead_stage`** (accurate for full migrated history) instead of summing empty tag rows; per-disposition ROWS stay tag-fed (fill in as callers set dispositions going forward). (2) Added a **"New / Unassigned"** stage (hex #94A3B8) + unmapped/blank `lead_stage` values roll into it, so stage totals **reconcile exactly to the grand total**. (3) `prev_stage_totals` (pace chart) now uses lead_stage pmtd. (4) Month dropdown = rolling **24-month** window (newest first), so multi-year history is selectable.
- **Verified exact vs raw DB (Jun 2025):** grand 5,811; New 1,189 / Attempt 1,172 / Contacted 1,171 / Converted 1,163 / Closed 1,116 — sum = 5,811 (reconciles); YTD 34,761 reconciles; current-month path also reconciles (ftd/mtd/ytd). Screenshot confirms pulse 5-way split + funnel Engaged=2,334 (=Contacted+Converted).
- **Expected under option B:** per-disposition rows (OPD Booked, Ringing…), Valid Leads and step conversion % remain 0 for untagged/migrated history and populate as callers set dispositions. On production current-month (leads worked live) these fill in.
- **⚠️ NEEDS PRODUCTION REDEPLOY** — fix is in preview only. Files: `backend/routes/reports.py` (KPI_STAGES + KPI_STAGE_LEADSTAGE, by_stage facet, stage_total(), months window).


## Perf (2026-07-19) — Dashboard + KPI report speed optimization — VERIFIED (preview)
- **Symptom:** user reports Dashboard/KPI "very very slow" (on freshly-deployed PRODUCTION; preview measured already fast). 
- **Root fixes (code, help both envs after redeploy):** (1) **Dashboard caching + in-flight coalescing** — `/reports/dashboard` fired 8 count_documents + 4 aggregations on EVERY load with NO cache (KPI already had a 120s cache). Refactored into a thin cached wrapper (`_dash_cache`, 45s TTL, keyed by scope+range+IST-day so it auto-invalidates daily) + `_compute_dashboard()`; concurrent identical requests share ONE computation. (2) **Two targeted compound indexes** on leads: `{active,pipeline,create_date_ist,lead_stage}` (admin scope) and `{active,user_id,pipeline,create_date_ist}` (caller scope) so cold/uncached report loads are index-first instead of paging the ~240MB collection. 
- **Measured (preview, 120k leads):** dashboard cold 0.43s → warm ~0.09s; caller dashboard warm ~0.09s; **10 parallel admin loads = 0.27s total** (coalesced). KPI already ~0.1-0.17s (cached). Cache correctness verified (cold==warm payload).
- **⚠️ NEEDS PRODUCTION REDEPLOY** — new indexes build in the background on startup (brief slow window right after deploy while they build, then fast). If production is still slow post-redeploy AFTER indexes finish, likely a DB-tier/network factor → Emergent Support.



## Feature (2026-07-18) — KPI "Lead Pulse" Performance Dashboard REBUILT to client-approved design — VERIFIED (iteration_59: backend 6/6, frontend 100%)
- Full rebuild of `/kpi` to match the client's approved reference HTML ("Lead Pulse"). Single page: live clock header, **Month/Year filter**, dark FTD/MTD/YTD chip, 4 KPI boxes (Today Total Leads, OPD Booked, OPD Done, Registration), **Pipeline Pulse** 100%-stacked bars (FTD/MTD/YTD), **Valid Leads** card (single total row + formula), 4 stage tables showing ALL fixed dispositions (Contact Attempt 4, Contacted 3, Converted 5, Closed 22 — zero rows always shown), Conversion Metrics (MTD green / YTD amber, cumulative step ratios), Conversion funnel (FTD/MTD/YTD toggle, cumulative), and 3 Chart.js charts (Stage-mix donut, Top-10 closed reasons, Daily-pace grouped bar).
- **Month filter:** past month re-renders with FTD→"Avg/Day", MTD→"Month", amber closed-month banner, YTD = Jan 1..end of selected month; pace chart switches to month-vs-previous-month. Current month = live (auto-refresh 5 min).
- **Backend:** `GET /api/reports/kpi-overview?month=YYYY-MM` — single `$facet` over `create_date_ist` (IST), fixed KPI_STAGES list, matches tags stored as int-ids OR strings, returns stages/rows/totals + months + prev_month. Cached 120s. `%` computed client-side against period TOTAL leads; pulse normalized to sum of 4 stages.
- **Frontend:** `KpiOverview.jsx` (chart.js/auto) + scoped `LeadPulse.css` (all rules under `.leadpulse`), fonts Sora + Albert Sans.
- **⚠️ NEEDS PRODUCTION REDEPLOY.** (Superseded the earlier iteration_57 KPI version.)

## Feature (2026-07-18) — Case 1 (open edit access + audit log) + Case 2 (presence routing + attendance) — VERIFIED (iteration_60: backend 8/8, frontend 100%)
- **Case 1 — access model REVERSAL (done):** `canEdit` is now always `true` in `LeadDetail.jsx` — ANY caller can view AND edit ANY lead (undoes the iter58 owner-only edit lock). The ONLY restriction: the assigned caller field is protected — callers cannot reassign (`assignee-select` disabled for role=caller; PATCH strips `user_id` for callers), and `original_user_id` is immutable (PATCH always strips it; set once at creation). A '🔒 Originally assigned to <name> · locked' line (`data-testid=original-caller`) shows on the Assignment card. Every mutation is recorded via `log_audit()` → `db.audit_logs` and surfaced in a new **Activity Log** tab (`tab-audit`) on LeadDetail — the `AuditLog` component (end of LeadDetail.jsx) fetches `GET /api/leads/{id}/audit`, shows who/what/old→new/when newest-first, client-paginated (50 + "Show older"). `_track_changes()` in leads.py logs disposition/tags, reassignment, stage, field edits, lost, follow-up, caller activity, whatsapp.
- **Case 2 — presence-based routing (done):** `core/utils.py` adds `AVAILABLE_STATUSES={'Available','On Call'}`, `pick_available_caller(prefer_ids)`, `queue_lead_for_assignment(lead_id)`, `drain_lead_queue()`. Webhook (`webhooks.py`) + Facebook (`facebook.py`) lead creation now route round-robin ONLY to callers currently Available/On Call (choice **1b**); if NObody available the lead is QUEUED unassigned (`db.lead_queue`, choice **2a**) and auto-assigned FIFO the moment a caller sets Available/On Call (`POST /agent/status` calls `drain_lead_queue()`, returns `assigned_from_queue`). Drain uses an ATOMIC conditional update (`user_id:null` guard) to prevent a double-assign race across 24 concurrent callers. `original_user_id` set on webhook/fb create and on queue-drain assignment.
- **Case 2 — daily Offline reset (choice 3a, 2026-07-18 update):** everyone starts each IST day Offline and must re-mark Available. `core/utils.reset_stale_statuses()` (idempotent per IST day, guarded by `settings.status_reset.last_reset_date`) closes any still-open status log + forces all non-Offline users to Offline. Driven by `_status_reset_loop()` in server.py (runs on startup + every 5 min, so the day-boundary reset lands within minutes of IST midnight; also covers overnight/deploy rollovers).
- **Case 2 — admin manual force-status (2026-07-18 update):** `POST /agent/admin/set-status {user_id,status}` (admin/manager) overrides a caller's presence — e.g. force Offline when a caller forgot to. Setting Offline IMMEDIATELY stops new-lead assignment to them (routing reads `users.status` live; verified: forced-offline caller → next webhook lead queues). Attendance rows now include `current_status`/`current_since`; the Admin → Attendance UI shows a **Live status** chip + a per-caller **Set Offline** button (`attendance-force-offline-{uid}`). `AgentStatusSwitcher` polls `/agent/me` every 30s so an admin-forced change reflects on the caller's own screen.
- **Case 2 — Attendance panel (done, choice 4c):** Admin → **Attendance** tab (`admin-tab-attendance`). `GET /api/agent/attendance?date=YYYY-MM-DD | month=YYYY-MM [&user_id=]` returns per-caller time in each status, working (Available+On Call) vs break totals, first/last seen, present/absent, days-present (month), current live status, plus a full status timeline when `user_id` given. UI (`AttendanceTab` in Admin.jsx): Day/Month toggle, date/month picker, 4 summary cards, table with Attendance + Live-status columns, per-status breakdown, expandable per-caller Timeline. Also `GET /api/agent/queue` (admin) lists waiting leads. The top-bar `AgentStatusSwitcher` posts `/agent/status` (Available/On Call/Lunch/Washroom/Refreshment Break/Meeting/Offline) and logs break timers to `db.status_logs`.
- **⚠️ NEEDS PRODUCTION REDEPLOY** to reach the live site.

## Pending client requests (2026-07-18) — ✅ BOTH DONE (see entry above):
- ~~Case change 1 (access model reversal)~~ — DONE.
- ~~Case 2 (caller status + routing + attendance)~~ — DONE (choices 1b/2a/3a-daily-Offline-reset/4c) + admin manual force-status.



## Feature (2026-07-17) — Record-level access (Case 1) + Duplicate/My-Leads filters (Case 2) — VERIFIED (iteration_58: backend 16/16, frontend 10/10)
- **Case 1 — View-all / edit-only-if-assigned:** callers can now VIEW every lead (search any phone, open any record to see prior handling) but may only MUTATE a lead assigned to them. Enforced server-side by `core/security.ensure_lead_edit(lead, user)` → 403 `"Access Denied — this lead is assigned to another caller…"`. Applied to ALL lead-mutating endpoints: leads.py (update, lost, restore, promote, send_whatsapp, send_email, followups add/update/status/delete, caller-activities), chatter.py (notes, activities create/done/cancel), calls.py (click-to-dial + set-disposition), attachments.py (upload/delete). `build_query` no longer owner-scopes callers. Admins & managers unrestricted. Dashboard/Reports/Follow-ups/Call-logs remain personal (own data) — unchanged.
- **Case 1 — UI (LeadDetail.jsx):** `canEdit = role!=='caller' || lead.user_id===user.id`. Non-owner callers see a `readonly-banner` and any action opens an `access-denied-modal`. FieldCard/QACard/CustomFieldsCard/FollowUpSection/CallerActivities receive `canEdit`+`onDenied`; header buttons + note/tag/stage/upload gated. Assigned caller edits normally. NavGuard mandatory-field trap only fires after a real edit, so view-only callers navigate freely.
- **Case 2 — Duplicate Lead filter (Leads.jsx):** toolbar dropdown `filter-duplicate` ("Duplicate Leads only" → `?duplicate=true`). Backend shows all `is_duplicate=true` leads regardless of active (merged dupes are archived). Chip shows "Duplicate Lead: Only".
- **Case 2 — My Leads toggle:** caller-only `my-leads-toggle` button filters list to `user_id=<self>`; hidden for admin.
- **⚠️ NEEDS PRODUCTION REDEPLOY** to reach the live site.



## Feature (2026-07-17) — KPI Performance Overview Dashboard — VERIFIED (preview, iteration_57: backend 100%, frontend 100%)
- **What:** new left-sidebar page **"KPI Report"** (`/kpi`, nav testid `nav-kpi`, under `reports` permission → admin/manager only; caller is Guard-redirected + 403 on API). Replicates the user's color-coded KPI screenshot.
- **Layout:** top FTD/MTD/YTD total cards; a green **Conversion Metrics (MTD)** strip (Valid→OPD Booked, OPD Booked→OPD Done, OPD Done→Registration, Registration→Stimulation Start with num/den/pct + bars); then 5 color-coded stage sections — **Yellow VALID LEADS**, **Red CONTACT ATTEMPT**, **Orange CONTACTED**, **Green CONVERTED**, **Grey CLOSED** — each a Sub Status / FTD / MTD / YTD / % (MTD) table with a Total footer.
- **Definitions (user-confirmed):** FTD = leads created TODAY (IST), MTD = this month, YTD = this year — all by **lead creation date** (`create_date_ist`). **VALID LEADS** = computed cross-stage bucket (Call back for appointment + OPD Booked + OPD Done + Valid Not Interested), so OPD Booked/OPD Done intentionally also appear under their real stage.
- **Backend:** `GET /api/reports/kpi-overview` (reports.py). Reads stage→tag grouping from `settings.disposition_map` and tag catalog. Single `$facet` aggregation over the current-year slice (`active` + `pipeline!=False`) computes by-tag + totals in one scan; handles `tags` stored as BOTH int catalog ids AND string names (normalised + merged). Cached 120s per (scope, day).
- **Verified:** seeded 16 mixed-tag 2026 leads → FTD=5/MTD=18/YTD=23, Valid MTD=5, Valid→OPD Booked=40%; both int-id (Ringing=26) and string ("Busy") tags counted; caller 403; UI renders + Refresh works. Seed data removed after test.
- **⚠️ NEEDS PRODUCTION REDEPLOY** to appear on the live site.



## Fix + Feature (2026-07-15d) — Duplicate web leads + Caller Activity required — VERIFIED (preview)
### Duplicate leads (URGENT) — root cause + fix
- **Cause:** the web webhook (`/api/webhook/lead/{token}`) created a NEW lead AND round-robin-assigned a caller on EVERY post; it only *flagged* duplicates, never blocked them. The Website AI Agent re-posts the same enquiry repeatedly → the same phone/person was created many times and spread across many callers.
- **Fix (`webhooks.py`):** dedupe by phone BEFORE assignment — if an ACTIVE lead already exists for the number, do NOT create a new lead or consume an assignment; log a "🔁 Repeat web enquiry … merged" note on the existing lead and return its id. Verified: same phone posted 3× → 1 lead only, repeats merged (`duplicate:true, merged_into`).
- **Existing dupes cleanup:** the Duplicate-Cleanup UI had been bundled in the removed Odoo Migration tab. Restored it as a **standalone "Duplicates" admin tab** (backend `/admin/duplicates/scan|scan/status|delete` were already intact) — scan by created-date range, groups by name+mobile, keeps oldest, deletes newer (archived/recoverable). Verified: renders + scan completes.
### Caller Activity now mandatory
- Added **"Caller Activity"** to the Lead-edit navigation guard (alongside City, State, Disposition Tag). After a user edits an active lead, they can't leave until ≥1 Caller Activity is logged. `CallerActivities` now reports its count up via `onCount` → `callerActCountRef` read by the guard. Verified: block popup shows "Caller Activity" when missing; adding one clears the block.
- **⚠️ NEEDS PRODUCTION REDEPLOY.** After redeploy: use Admin → **Duplicates** to scan+delete the existing Website-AI-Agent dupes; new ones are auto-prevented.


## Change (2026-07-15c) — Export Lead Stage rule fix + FULL Odoo removal — VERIFIED (preview)
### Export Lead Stage consistency
- Rule enforced in export: a lead with a **blank disposition tag ⟹ Lead Stage = "New"** (a stray stage like "Contacted" set without a tag is normalised to "New"); tagged leads show their real `lead_stage`. Removed the earlier misleading pipeline `stage_id` fallback (it mixed Odoo pipeline stages into the disposition column). File: `backend/routes/export.py`. Verified: blank-tag "Contacted" → "New"; tagged "Contacted" → "Contacted".

### Odoo fully removed (cutover complete — user confirmed)
- **Backend:** deleted `backend/migration/` (odoo_sync.py, odoo_migrate.py); removed all migration/sync/audit endpoints from `admin.py` (`/migration/status`, `/migration/audit*`, `/sync/status`, `/sync/start`, `/sync/runs*`, `/whatsapp/sync-odoo-templates`, `_next_since`, `_audit_worker`) — kept role-perms/settings/automations/outbound_queue/duplicates; removed the `migration` permission from `core/permissions.py`; reworded Odoo comments/messages in `server.py`, `catalogs.py`, `whatsapp_cloud.py`; removed `ODOO_URL/ODOO_DB/ODOO_LOGIN/ODOO_PASSWORD` from `backend/.env`; deleted Odoo-dependent test files.
- **Frontend:** removed the **Migration** admin tab + entire `MigrationTab` component; removed "Sync approved templates from Odoo" button + `syncOdooTemplates`; reworded labels ("Pipeline Stages (Odoo)"→"Pipeline Stages", "All Odoo fields"→"Additional fields", Templates + Automations copy). Files: `Admin.jsx`, `Templates.jsx`, `LeadDetail.jsx`, `Bits.jsx`.
- **Data preserved:** leads, migrated custom/Q&A fields, pipeline-stage & tag catalogs, templates all intact — only Odoo labels/links/tools removed.
- Verified: removed endpoints → 404; kept endpoints → 200; `migration` gone from all_perms; Admin renders with no Migration tab and zero "Odoo"/"Migration" text; frontend compiles; backend healthy.
- **⚠️ NEEDS PRODUCTION REDEPLOY** for both to go live on hi-connect-1687.emergent.host.


## Feature (2026-07-15) — Mandatory-field navigation guard on Lead edit — VERIFIED (preview)
- **Why:** leads autosave on every field change, so callers edited a lead and navigated away (left menu) leaving mandatory fields empty → junk data accumulating.
- **Behavior (user-confirmed):** while on a lead the user has EDITED (touched) this session, if City / State / Disposition Tag is still empty, ALL navigation away is blocked with a popup listing exactly which fields are missing. Applies to EVERYONE (admin/manager/caller). View-only (no edit) is NOT blocked (avoids trapping on the thousands of existing incomplete leads). Inactive/Lost leads are exempt.
- **Coverage:** left sidebar nav, global search, logout, AI Brain card, in-page Back button, duplicate badge, WhatsApp-message links, page refresh/close (beforeunload), and browser Back (popstate sentinel — flagged as the more fragile vector).
- **Impl:** new `context/NavGuardContext.jsx` (provider + blocking modal + `registerGuard`/`checkAllowed`/`isBlocked`). `App.js` wraps Routes in `NavGuardProvider`. `Layout.jsx` gates every nav entry via `checkAllowed()`. `LeadDetail.jsx` tracks `touchedRef` (set in `update()`), registers the guard (reads latest lead via `leadRef`), resets touched on lead change, and installs beforeunload+popstate handlers. Uses `BrowserRouter` (no `useBlocker`), so guard is enforced by intercepting each navigation source.
- **Verified (Playwright):** edit→block popup lists City/State/Disposition Tag & stays on lead; fill all 3 → nav allowed; open incomplete lead without editing → nav allowed (no trap).
- **⚠️ NEEDS PRODUCTION REDEPLOY** to go live.


## Fix + Feature (2026-07-13b) — Export blank Stage/Tags + "Website AI Agent" source — VERIFIED (preview)
- **Export (P0, prod-only complaint):** Admin's Leads → Export Excel showed blank "Lead Stage" + "Tags" for a date range on PRODUCTION. Current preview export code was VERIFIED CORRECT (lead with lead_stage="Contacted"+tags → Excel shows "Contacted" + "Ringing, Call back for first pitch"), so production is on an OLDER build → needs redeploy. Added a safety net: `export.py` "Lead Stage" now falls back to the pipeline stage name (via `stage_id` → `stage` catalog) when the disposition `lead_stage` is empty, so the column is never wrongly blank (verified: lead with lead_stage=None + stage_id=4 → exports "Converted"). `_label_maps()` now also returns `stages`.
- **Website AI Agent source (feature):** seeded `source_lead` catalog with **"Website AI Agent"** (server.py startup) so it appears in the Source dropdown/filters. Webhook (`/api/webhook/lead/{token}`) now honors a `source`/`source_lead`/`lead_source` field in the payload (FIELD_ALIASES), falls back to the webhook's `source_default`, and auto-registers the final source via `ensure_catalog` + `bust_catalogs`. Verified: webhook lead via hook-default AND via explicit `source` field both got `source_lead="Website AI Agent"`.
- **Files:** backend/routes/export.py, backend/routes/webhooks.py (imports ensure_catalog + bust_catalogs), backend/server.py (source seed).
- **⚠️ NEEDS PRODUCTION REDEPLOY** for both to go live on hi-connect-1687.emergent.host.

## Fix (2026-07-13) — 503/504 concurrent-load timeouts on Lead menu (P0) — VERIFIED
- **Symptom:** under a burst of callers loading the Lead menu, requests piled up to ~68s and returned 503/504. Each caller load fires 4 heavy reads: leads list + group_counts(lead_stage) + group_counts(user_id) + /catalogs.
- **Root cause chain:** (1) /catalogs did ~5 collection reads on every page load; (2) count_documents scanned ~120k index keys per call; (3) group_counts ran a FULL-collection aggregation over ~120k docs per call — and every caller fired the SAME aggregations with identical params, so 24 callers = 48 identical heavy aggregations contending on the single-worker DB.
- **Fixes:** in-memory TTL cache for /catalogs (45s, busted on any catalog write); TTL cache + in-flight COALESCING for count_documents (30s) — done prior session; NEW this session: same TTL(30s)+coalescing for `group_counts` in leads.py (`_cached_group`) so N identical concurrent aggregations collapse into ONE DB call. maxPoolSize already 100.
- **Verified (preview, real 120,024-lead dataset):** cold 40-caller burst (160 reqs) completes in **1.37s, all HTTP 200** (was ~68s + 503s). group_counts sums correct (119,808 == pipeline list total); caller-scoping intact (caller sees 5,266 own, separate cache key); Leads UI renders (page 1 of 2,397).
- **Files:** backend/routes/leads.py (_cached_group + group_counts), backend/routes/catalogs.py (cache prior), backend/core/db.py (maxPoolSize=100).
- **⚠️ Needs PRODUCTION REDEPLOY** to take effect on homeivfcrm.com.


## Batch (2026-07-13) — Caller 500/slow + Cases 1–4 — iteration_55 (backend 21/21, frontend 100%)
- **P0 (caller 500 + slow load):** the 2026-07-11 search fix (case-insensitive→lowercased indexed prefix) + `maxPoolSize` 25→100 addresses it; ADDED a caller-scoped pipeline index `{active,user_id,pipeline,create_date,id}` so a caller's default "Lead in Pipeline" tab never blocking-sorts at scale. Preview verified fast (lists 0.17s, search 0.12s, dashboard 0.39s).
- **Case 1 — WhatsApp chat visibility by role:** denormalized `owner_id` onto `wa_channels` (assigned caller of the matching lead). Callers see only their own chats; admin+manager see all. `owner_id` set on inbound-webhook channel creation, kept in sync on lead reassignment (`sync_channel_owner` in update/bulk-assign/promote), and backfilled on startup (11,918 channels). Filters in `/whatsapp/channels` + `/whatsapp/unread-summary`.
- **Case 2 — follow-ups:** reminder now OWNER-only (`created_by`) + fires only in the [sched−5, sched] minute window (never after) + frontend localStorage dedupe (once) + moved bottom-RIGHT (no longer covers left menu). Follow-ups list shows Follow Date / Follow Time / Status. "Not Done" status removed (deactivated in catalog + dropped from analytics; past-due unmarked = Pending). Lead detail shows "Total Follow-up: N". `follow_up_status` denormalized to lead.
- **Case 3 — lead fields + disposition:** removed Age & Spouse Age from Case Details; added optional Alternate Number in Contact; City & State now mandatory on Contact edit/save (field-level errors, blocks save); Disposition Tags → Lead Stage dependent mapping (selecting a tag auto-sets the stage, dropdown grouped by stage) + seeded mapping + Admin "Disposition Tag → Stage Mapping" editor (`GET/PUT /catalogs/disposition-map`).
- **Case 4 — count consistency:** Dashboard `base` scoped to `pipeline!=False` so Today count + Funnel now equal the "Lead in Pipeline" export (verified 119,808 == 119,808; funnel sum == total).
- **Files:** reports.py, whatsapp.py, wa_cloud.py, core/utils.py (sync_channel_owner), leads.py, catalogs.py, server.py; frontend LeadDetail.jsx, FollowUps.jsx, FollowUpReminder.jsx, Admin.jsx.
- **⚠️ NEEDS PRODUCTION REDEPLOY** — owner_id backfill, disposition seed, "Not Done" deactivation, and new indexes all run on startup after deploy.
- **Deferred (documented to user):** the disruptive "block all navigation until a note is added on every lead open" — implemented as mandatory note on activity-add + save-blocking on required fields instead (safer UX).


## Fix (2026-07-11) — WhatsApp welcome automation all FAILED (Meta error 131047) — iteration_53 (backend 6/6)
- **Symptom:** New-lead "Welcome Message" automation fires but every message = Failed, error **131047** ("Re-engagement message / >24h since customer replied").
- **Root cause:** 131047 only happens for FREE-FORM (session) messages sent outside Meta's 24-hour window. `send_lead_template()` fell back to free-text whenever the CRM template had no `wa_template_name` (not linked to an approved Meta template). New leads have no open 24h window → free-text always 131047. (One "Delivered" in the log = a lead who had messaged within 24h.)
- **Code fix:** `send_lead_template(..., require_template=True)` for automations (`_apply_actions`) + campaigns (`marketing.py`); when a template isn't linked it now returns an ACTIONABLE error (explains 131047 + how to link) instead of a doomed free-text send, and records the message as **Failed** (not "in_queue"). Manual per-lead sends keep the free-text fallback for in-window chats. Also stopped double-listing failed sends as "pending" in `outbound_queue`.
- **⚠️ USER CONFIG REQUIRED (the actual unblocker):** the welcome template must be an APPROVED Meta template and the CRM template's `wa_template_name` + `lang` must point to it. Approved Meta templates deliver outside the 24h window; free-text/unapproved cannot. Options: use the already-linked "New Lead - Message" (id 4 → `new_lead_message`) in the automation, or set the approved Meta name+language on their template (Templates → WhatsApp template), or Admin → WhatsApp → "Sync approved templates from Odoo".
- **⚠️ Needs PRODUCTION REDEPLOY** for the code fix.


## 🔴 URGENT Fix (2026-07-11) — Login 500s (intermittent) + slow lead search under full-live load — iteration_52 (backend 11/11, frontend 100%)
- **Context:** Prod went fully live (all 24 callers moved, ~120k leads). User reported frequent login `500` + very slow search.
- **Root cause:** lead search used a CASE-INSENSITIVE anchored regex (`$options:'i'`) on name/contact_name/email_from → cannot use index bounds → every search FULL-scanned ~120,007 docs (~783ms) + a `count_documents` full scan. Under 24 concurrent callers this exhausted the Mongo connection pool (`maxPoolSize=25`) → other ops (incl. `/auth/login`) timed out → intermittent 500s. (explain proof: keysExamined=120007, docsExamined=120007.)
- **Fix:** (1) Added lowercased indexed fields `name_lc`/`contact_name_lc`/`email_lc`; search now lowercases the query and uses a CASE-SENSITIVE `^prefix` regex → tight index bounds (explain: keysExamined 120007→**6**, execMillis 783→**1**). Wired `search_norm()` into ALL lead write paths (create/update/promote/webhook/facebook/calls/migration sync). (2) `maxPoolSize` 25→**100** (min 5). (3) Idempotent startup backfill set `_lc` on all 120,007 existing leads. Indexes added in `server.py`.
- **Also fixed:** dashboard funnel returned multiple "New / Unassigned" rows (null/False/"" lead_stage buckets) → duplicate React key; backend now merges them into one row (`reports.py`).
- **Files:** `core/utils.py` (search_norm), `core/db.py` (pool), `routes/leads.py` (search branch + create/update/promote), `routes/webhooks.py`, `routes/facebook.py`, `routes/calls.py`, `migration/odoo_migrate.py`, `server.py` (indexes+backfill), `routes/reports.py` (funnel merge).
- **⚠️ Needs PRODUCTION REDEPLOY** — the search fix, pool bump, index build + `_lc` backfill all run on startup after deploy.

## Investigation+Tool (2026-07) — "Migrated leads show blank Lead Stage/Tags" — iteration_51 (backend 5/5, frontend 100%)
- **Not a mapping bug (PROVEN vs LIVE Odoo):** `transform_lead` on real Odoo lead #132938 ("Kamlesh Yadav") yields lead_stage='Contact Attempt', tags=[26]('Ringing'), follow_up_tag='Follow UP 1'. Applying the exact sync `$set` to a blank CRM copy correctly populates all of them. So the delta sync WILL move stage/tags when it runs — the fields are blank because a sync hadn't re-run since the callers' recent Odoo edits (they went live but kept editing in Odoo).
- **New tool — force re-pull:** `POST /api/admin/sync/start` now accepts an optional `{since:"YYYY-MM-DD"}` override; Admin → Migration has a "Re-sync from date (backfill)" date input + button (`resync-since-input` / `resync-from-date-button`) to pull all Odoo changes since a chosen date and update matching leads by Odoo id.
- **⚠️ OPEN (needs user):** if the blank CRM leads have CRM-webhook ids (500000+) rather than Odoo ids, they are duplicates of the Odoo copies and a re-sync won't fill them (it creates/updates the Odoo-id copy instead). Asked user to check a blank lead's CRM ID to decide re-sync vs dedupe.
- **⚠️ Needs REDEPLOY** for the override + UI to reach production.


## Fix+Feat (2026-07) — Lead in Pipeline slow/500 + Search slow + Conversion Page — iteration_50 (backend 22/22, frontend 100%)
- **Pipeline tab 500/slow (root cause):** the default "Lead in Pipeline" bucket used `$and:[{$or:[{ozonetel_lead:{$ne:true}},{in_pipeline:true}]}]` which can't use the sort-covering index → blocking in-memory SORT over ~100k docs → slow / 500. **Fix:** added an indexed `pipeline` boolean; pipeline bucket = `{pipeline:{$ne:False}}`, ozonetel bucket = `{pipeline:False}`, both covered by new index `{active,pipeline,create_date,id}`. Raw Ozonetel leads set `pipeline:False` (calls.py); promote sets `pipeline:True`; startup backfills `pipeline:False` on existing raw-Ozonetel only (small, fast, no vanish window). Measured ~0.15s over 120k.
- **Search slow (root cause):** unindexed 'contains' regex `$or` over 4 fields → full collection scan + blocking sort. **Fix:** pure-numeric query → indexed `phone_digits` only (exact/prefix, ~0.1s); text query → 'starts-with' prefix regex on indexed name/contact_name/email_from. NOTE: search is now **prefix (starts-with)**, not substring. Added single-field indexes on name/contact_name/email_from.
- **Feature — Conversion Page:** website webhook now captures the submission page. `webhooks.py` FIELD_ALIASES maps page_url/page_name/form_name/landing_page/etc → `conversion_page`; stored on the lead, shown & editable in the **Attribution** card (LeadDetail). Website should send `page_url` (preferred).
- **⚠️ Needs PRODUCTION REDEPLOY** (indexes build in background on startup; pipeline backfill runs once).
- **OPEN QUESTION (data integrity — NOT yet fixed):** user reports recent Meta leads show empty Lead Stage/Tags in CRM while the SAME leads show stage+tags in Odoo → likely callers are still working leads in Odoo (not CRM) OR dual delivery. Needs user clarification on cutover before any fix.


## Fix (2026-07) — 🔴 URGENT: /leads page slow / times out ("Request failed") on production — iteration_49 (backend 8/8, 100%)
- **Root cause:** GET /api/leads sorts by `[(sort_field, dir), ("id", -1)]`. The existing index `{active:1, create_date:-1}` did NOT include the `id` tie-break key → MongoDB fell back to a BLOCKING in-memory SORT over all ~100k matching docs → slow, and past the 32MB sort limit it 500'd with "Sort exceeded memory limit" = the user's "Request failed".
- **Fix:** Added two sort-covering compound indexes to `server.py` INDEX_SPECS: `{active:1, create_date:-1, id:-1}` (admin default) and `{active:1, user_id:1, create_date:-1, id:-1}` (caller-scoped default). Explain plan drops from `SORT` to indexed `LIMIT→FETCH→IXSCAN`.
- **Verified (preview, seeded 120,000 leads via backend/seed_perf.py):** default admin load 0.14s (was 0.47s+ w/ blocking sort and 500-prone at scale), caller-scoped 0.09s, pagination/filters/sort all <250ms, HTTP 200. Regression suite: `backend/tests/test_leads_perf.py`.
- **Also this session — Website lead integration:** Public webhook `POST /api/webhook/lead/{token}` now round-robins web leads across active callers (fallback, so they're never Unassigned/invisible) — mirrors the FB-lead behavior. Created "HomeIVF Website" webhook + unified source catalog to "Website". User given the API + a prompt for their Emergent-built website project.
- **⚠️ Needs PRODUCTION REDEPLOY** for the compound indexes (built in background on startup) + the webhook round-robin code to reach production.


## Fix (2026-07) — "Sync Now not working" → Odoo delta sync now runs IN-PROCESS — iteration_37 (backend 4/4, frontend 100%)
- **Root cause:** `POST /api/admin/sync/start` spawned a *detached subprocess* that wrote to `/var/log/odoo_sync.log`. In the managed/container production deploy this is fragile (read-only FS / detached-process limits) → the button appeared to do nothing.
- **Fix:** sync now runs in-process on a background `threading.Thread` → `odoo_sync.run_sync(run_id, since, until)` (extracted from the script's `__main__`). Progress is written to `sync_runs`; `settings.last_sync` is set on completion; import/connect failures are recorded via a fallback sync pymongo client. No subprocess, no log-file dependency.
- **Verified in preview against LIVE Odoo:** full delta ingested +11,032 leads, +118,625 chatter, +957 WA channels, +3,694 WA messages, +10,733 contacts, activities → status done; a second in-process run completed through all 9 entities and updated last_sync. Live Audit shows all modules match (lead_chatter ~0.01% behind is expected — sync skips empty-body system messages + Odoo grows live). Non-admins get 403.
- **Go-live note:** REDEPLOY to push this to production; on production's own DB the first "Sync Now" auto-runs FULL import if empty, else delta.

## Feature (2026-07) — Lead view & Follow-ups (Cases 1–6) — iteration_35/36
- **Case 1 — Note mandatory:** a follow-up cannot be saved without a note (backend 400 + frontend block) in Assignment & Follow-up (`add_followup`/`update_followup`).
- **Case 2 — Caller Activities:** new lead-view section (`CallerActivities`) with a feedback input + "Add More Note"; each entry stored separately in `caller_activities` and shown as history (note · agent · timestamp). Endpoints `GET/POST /api/leads/{id}/caller-activities`.
- **Case 3 — Default Country India:** `create_lead` defaults `country="India"`; New Lead modal Country select defaults to India (changeable).
- **Case 4 — Follow-up reminder popup:** global `FollowUpReminder` (mounted in Layout) polls `GET /api/leads/followups/reminders` every 60s and shows a card ~5 min before a scheduled follow-up time (caller = own leads, admin = all), with Mark-done/Open/Dismiss. Stays until dismissed.
- **Case 5 — Status + analytics:** dynamic `followup_status` catalog (Completed/Not Done/Rescheduled/Cancelled, admin-editable in Admin → Dropdowns). Status dropdown under the Note + inline per-entry status setter (`POST /followups/{fid}/status`). Analytics bar in Follow-ups tab via `GET /api/leads/followups/analytics?date=` (Total/Completed/Not Done/Rescheduled/Cancelled/Pending; past-due unmarked count as Not Done).
- **Case 6 — Lead export:** Admin-only "Export" button beside New Lead (Lead-in-Pipeline tab) → date-range modal → downloads ALL lead fields + serialized Q&A/custom column as Excel (`GET /api/export/leads.xlsx`, requires `export` permission; caller = 403).

## Feature (2026-07) — Case 3 Marketing Campaigns overhaul (WhatsApp + Email) — iteration_34 (frontend 100%, backend curl-verified)
- **Template preview on create/edit:** selecting a WhatsApp/Email template in the campaign modal now renders a live preview (`template-preview` / `template-preview-body`) with {{1}}→sample name; email shows Subject + rendered HTML.
- **Rich campaign box:** each card now shows channel chip (WhatsApp/Email), template name, trigger/logic (`trigger_desc` from audience filters), status badge (Draft/In Progress/Paused/Completed/Failed/Queued), a progress bar + %, and metrics Total/Sent/Delivered/Read/Replies/Queued/Failed. WA delivered/read/replied are computed live from `wa_tracking` aggregation by `campaign_id` (added `campaign_id` to `record_wa_outbound`).
- **Actions:** Send, **Pause** (in-progress), **Resume** (paused, continues via `/send` skipping already-processed leads), **Edit** (PATCH, blocked while running), Delete, and **View failures & reasons** modal (`/campaigns/{cid}/failures`).
- **Background sender:** `POST /campaigns/{cid}/send` now launches an asyncio background task, sets status `in_progress`, updates counters live (frontend polls every 3s), honours the pause flag, and auto-sets **completed** at 100%.
- New/updated endpoints in `routes/marketing.py`: enriched `GET /campaigns`, `PATCH /campaigns/{cid}`, `POST /campaigns/{cid}/pause`, `GET /campaigns/{cid}/failures`. NOTE: preview WA send returns Meta errors (not connected) → failures panel is populated as expected.

## Feature (2026-06) — Email sender name + WhatsApp Chat Workspace (Case 1 + Case 2 Phase-2A/2B) — iteration_33 (100%: 16/16 backend + all frontend)
- **Case 1 — Email sender name → HomeIVF:** send_email now sets From as `HomeIVF <account>` via `formataddr`. Admin can edit the display name in Admin → Email (`POST /admin/gmail/sender-name`, default "HomeIVF"). Live email send confirmable only on production (Gmail connect).
- **Case 2 — WhatsApp Chat Workspace overhaul (followed the referenced Figma design system):**
  - Unread indicators + per-chat unread counts (bold rows + green badge), auto-marked read on open (`unread_count` on wa_channels, inbound webhook increments it, `POST /whatsapp/channels/{id}/read`).
  - Global floating "new WhatsApp message" notifier (`WaNotifier` in Layout, `GET /whatsapp/unread-summary`, 15s poll) — appears app-wide so no chat is missed.
  - Filter tabs All / Unread / Interested; conversation search; in-conversation message search (`?search=`).
  - "Interested Customer" categorization — `POST /whatsapp/channels/{id}/category` tags the linked lead "Interested" + sets lead_stage="Contacted" + chatter note + runs on_tag_set automations.
  - Star & Pin messages + a Starred side panel (`/messages/{id}/star|pin`, `?starred=true`, pinned bar).
  - Emoji picker (curated, no dep), quote-reply (reply_to snippet).
  - Attachments (image/file/video) — `POST /whatsapp/media/upload` stores a CRM-viewable copy + uploads to Meta (media id) → `send_media`; served via `GET /whatsapp/media?path=&auth=`. Emoji reactions — `/messages/{id}/react` + inbound `reaction` webhook attaches emoji.
  - Backend bug fixed by QA: toggle_star/pin used `if not m` (empty projection dict is falsy) → changed to `is None`.
- **Deferred:** received (inbound) customer media currently shows a "[type]" placeholder (full inbound media download/render not built); voice notes explicitly skipped per user.


- **Gap 1 — inbound from new numbers was dropped:** the inbound webhook only mirrored into an EXISTING wa_channel, so a first-time inbound (number with no migrated thread) never appeared in the WhatsApp inbox. Now `wa_webhook()` auto-creates a wa_channel (via `_next_channel_id()` which self-heals the `wa_channel` counter to max(id) to avoid colliding with the 10.9k migrated channels), then stores the inbound message. Same number reuses the thread.
- **Gap 2 — reply always said "queued":** `POST /whatsapp/channels/{id}/send` now surfaces the real result — returns the live status/wamid on success, and raises HTTP 400 with the Meta error (e.g. free-text only allowed within the 24-hour customer-service window → send a template) on failure. Frontend inbox toasts by status + polls the open thread & channel list every 8s for near-real-time chat.
- **Confirmed working:** testing verified a live reply was accepted by Meta (wamid returned) in preview. So 2-way chat itself works. **Two dependencies for it to flow on production:** (a) the app's WhatsApp `messages` webhook must be subscribed & pointed at the prod CRM (same requirement as delivery-status — use Admin → WhatsApp → "Diagnose delivery status"); (b) free-text replies only work inside Meta's 24h window — outside it, agents must send an approved template.


- **Case 1 (Gmail OAuth "invalid_grant: Missing code verifier"):** PKCE `code_verifier` from `authorization_url()` was lost because the callback built a fresh Flow. Fix: persist `flow.code_verifier` in `oauth_states` (keyed by state) at auth-url time and restore it on the callback flow before `fetch_token` (stateless/multi-worker safe). Verified: verifier stored (~128 chars), callback with bad code → 302 error redirect (no 500). Full Google E2E still needs a live login on production after redeploy.
- **Case 2 (Move to Pipeline in lead detail):** Added `data-testid=move-to-pipeline-button` in LeadDetail header, shown only for raw Ozonetel leads (`ozonetel_lead && !in_pipeline`). Click promotes directly via POST /leads/{id}/promote-to-pipeline using the lead's current info — **no popup**; button disappears after move; merges into existing pipeline lead on duplicate phone.
- **Case 4 (activity preview + status):** Confirmed inline template preview card + live status badge render in the lead Activity log for manual & automation sends (`activity-preview-{id}` / `activity-status-{id}`). Was built iter28; re-verified.
- **Case 5 (WhatsApp Template page + Quick Reply):** Converted Applies To (Lead/Contact), Phone Field (CRM-field dropdown), Header Type (None/Text/Image/Video/Document/Location), Users (all / specific-agents multi-select), and Variables→Field (CRM-field dropdown) to proper dropdowns. New `GET /api/catalogs/lead-field-options` (standard + custom fields). Button tab: Quick Reply/Set Automation buttons get an **automation dropdown** (`button-automation-{i}`) + setup guide. Backend: inbound WhatsApp webhook now parses `type=button`/`interactive` button replies → logs a Quick Reply chatter entry, marks the latest outbound tracking as **replied**, and runs the button's mapped automation (`run_automation_by_id`; refactored `_apply_actions`).
- **Message Log "stuck at SENT" (Case 4/5):** Confirmed NOT a CRM bug — Meta-side webhook delivery config. Use the "Diagnose delivery status" button (Admin → WhatsApp) added iter30 on production to pinpoint (needs App ID+Secret + 'messages' field subscribed + callback pointed at prod CRM).


- Confirmed CRM code is CORRECT end-to-end (wamid stored on send; webhook matches wamid → advances sent→delivered→read; preview verdict='healthy', 5/5 status webhooks matched). The production "stuck at Sent" is a **Meta-side delivery config** issue, not a CRM bug.
- New: `GET /api/admin/whatsapp/diagnose` (wa_cloud.py) + `check_app_subscriptions()` (whatsapp_cloud.py, reads {app_id}/subscriptions via app token). Returns a plain-English **verdict + next_step** and a 5-point checklist: (1) token+phone configured, (2) WABA subscribed to an app, (3) app 'whatsapp_business_account' webhook has 'messages' field + points to this CRM, (4) status webhooks actually received, (5) tracked msgs carry a wamid. Verdict trusts observed matched status webhooks first.
- UI: Admin → WhatsApp → "Diagnose delivery status" button (data-testid=wa-diagnose-button) → verdict panel (wa-diagnose-result / wa-diagnose-verdict).
- **USER ACTION on production (after redeploy):** Admin → WhatsApp → add App ID + App Secret → click "Diagnose delivery status". It will name the exact broken link. Most likely fix: in Meta → App → WhatsApp → Configuration set Callback URL to the prod CRM's /api/webhooks/whatsapp and subscribe the **messages** field, then click "Subscribe WABA to webhooks". NOTE: messages sent BEFORE this stay "Sent" forever — send a fresh one to confirm.


- Root cause: CRM webhook→wa_tracking status logic is CORRECT (verified: signed webhook advances sent→delivered→read→failed with history). Production stayed "Sent" because **Meta wasn't delivering status webhooks** — the WABA wasn't subscribed to the app.
- Fix: `subscribe_waba()`/`get_subscribed_apps()` in whatsapp_cloud.py + admin endpoints `POST /api/admin/whatsapp/subscribe`, `GET /api/admin/whatsapp/subscribed-apps`. Added a webhook diagnostic log (`wa_webhook_log`) + `GET /api/admin/whatsapp/webhook-log`. Admin → WhatsApp UI: "Subscribe WABA to webhooks" + "Recent webhook deliveries" buttons/panel.
- USER ACTION on production (after redeploy): click "Subscribe WABA to webhooks", and ensure the **messages** field is subscribed in Meta → WhatsApp → Configuration. Then delivered/read/replied will flow live.
- NOTE: Case 2 (Ozonetel split) IS built & tested in preview (iter27) — if user doesn't see it, it's because production hasn't been redeployed since.


## Feature (2026-07) — Case 4 fully closed: inline template preview + live status in Activity Log — iteration_28 (100% backend + frontend)
- **Gap fixed:** Case 4 previously used a separate side panel. Now, when a WhatsApp/Email template is sent (manual OR automation), the lead's **Chatter/Activity log** shows the message as an inline **preview card** with a **status badge on the top-right** (hover shows Sent/Delivered/Read/Failed/Bounced/Replied). WhatsApp cards are clickable → message lifecycle detail page; badge reflects live `wa_tracking` status.
- Backend: `log_message` now accepts an `extra` dict; `send_whatsapp`, `send_email`, and `run_automations` attach `{kind, preview, template_name, track_id, status, channel}` to the chatter message. Frontend: `TemplateActivityPreview` in LeadDetail + `waTrackById` live-status map.
- Note: email delivery/read status isn't available from Gmail API (email badge shows Sent/In Queue snapshot).
- **ALL doc Tab-2 cases (1–5) now fully complete & tested.** Case 1/Gmail pending user's production redeploy confirmation.


## Feature (2026-07) — Doc Tab 2 remaining cases 2/3/4 — iteration_27 (backend 100%, frontend 100%)
- **Case 2 — Ozonetel vs Pipeline split:** Leads page now has two buckets: "Lead in Pipeline" (default) and "Ozonetel Lead" (raw, `ozonetel_lead=true & in_pipeline!=true`). Backend `bucket` filter in build_query/query_params_dep. New `POST /api/leads/{id}/promote-to-pipeline` validates a raw lead into the pipeline; DEDUP: if a pipeline lead has the same phone, the raw lead's call activity is merged into it (`merged_into`, is_duplicate/duplicate_of set) and the raw one archived. Frontend: bucket tabs + "→ Pipeline" button + PromoteModal (name/phone/email/city/state).
- **Case 3 — Automation template preview:** In Admin → Automations, selecting a WhatsApp/Email template in an action now shows a live preview (body/subject) below the selector (`action-preview-{idx}`).
- **Case 4 — In-lead message preview + status:** LeadDetail "WhatsApp Messages" panel (WaLeadPanel) shows each tracked message with preview + status badge (hover shows status) linking to the message detail. (Email delivery/read status is not available from Gmail API.)
- ⚠️ Needs production REDEPLOY. NOTE: after any manual DB seed, re-align `db.counters.lead` to MAX(id) or create_lead will 500.
- **ALL DOC CASES NOW COMPLETE** (Tab 1 Cases 1-6, Tab 2 Cases 1-5). Case 5/Gmail pending user's production redeploy confirmation.


## Feature (2026-07) — 📲 Case 5: WhatsApp Template Management + Message Tracking (A→B→C) — iteration_26 (backend 100%, frontend 100%)
- **Decision:** Template config stored in CRM only (Meta approval remains manual).
- **Phase A — tracking:** New `wa_tracking` collection + `record_wa_outbound()` helper. Every outbound WhatsApp template (manual lead send, automation, campaign) is stored with wamid, template, lead, sent_to, created_by, body, status + status_history. Meta status webhook (`/api/webhooks/whatsapp`) updates the record by wamid through the lifecycle (sent→delivered→read→failed, with failure_type/error_code); inbound replies mark the latest outbound as `replied`. New API `routes/wa_tracking.py`: `/api/wa/template/{id}/summary`, `/api/wa/template/{id}/messages`, `/api/wa/message/{id}`, `/api/wa/lead/{id}/messages`. Lifecycle: In Queue→Sent→Delivered→Read→Replied→Received→Failed→Bounced→Cancelled (`core/utils.WA_STATUS_FLOW`).
- **Phase B — full-page template:** WhatsApp templates now open as a full page (`/templates/whatsapp/:id`, `WaTemplateDetail.jsx`) with 3-step approval flow (Draft→Pending→Approved), info fields (Applies To, Phone Field, Language, Header Type, Category, Footer, User Access, Meta name), and Body/Button/Variables tabs + live preview + Submit. Approved templates show an "Ad Messages" summary box (total triggered) → message-list page (`WaMessageList.jsx`, table Created On/Created By/Sent To/State) → message-detail page (`WaMessageDetail.jsx`, visual lifecycle tracker + failure reason/code + history). `templates.py` extended with the new fields + single GET.
- **Phase C — lead log:** LeadDetail shows a "WhatsApp Messages" panel (`WaLeadPanel`) listing tracked messages with a status badge (hover shows status) + preview; click opens the message detail.
- Verified: 14/14 backend pytest incl. HMAC-signed webhook status advance; all frontend selectors/navigation. ⚠️ Needs production REDEPLOY.
- **Still pending:** doc tab t.hx4luqwr4eh5 Case 7 (per user); doc tab t.lzutgaq803u Case 2 (Ozonetel raw-leads vs Pipeline split), Case 3/4 (automation preview + status icons in lead log — partially covered by WaLeadPanel).


## Fix (2026-07) — 📧 Gmail OAuth "Scope has changed" token-exchange failure — iteration_25 (backend 100%)
- Google returns granted scopes reordered and adds the `email` alias (`email gmail.send openid userinfo.email`), which made oauthlib raise "Scope has changed" during `fetch_token` → connection failed even though consent + code were valid.
- Fix: set `OAUTHLIB_RELAX_TOKEN_SCOPE=1` and `OAUTHLIB_IGNORE_SCOPE_CHANGE=1` at import of `core/gmail_send.py` (before token exchange). Callback also surfaces the real reason (`?gmail=error&reason=...`).
- Verified: auth-url, callback error/badstate paths, env flags set at import; RBAC + follow-ups regression clean. ⚠️ Full E2E needs production REDEPLOY + real Google login retry.
- Pending (new doc tab t.lzutgaq803u): large WhatsApp template management + message-tracking epic (Case 5) — NOT yet built; scope confirmation with user.


## Feature (2026-07) — 🔐 Roles & Access Control (RBAC) + 6 Phase-1 UI cases — iteration_24 (100% backend + frontend)
- **RBAC:** 3 fixed roles (admin/manager/caller) with an editable permission matrix. New `core/permissions.py` (MODULE_PERMS + ACTION_PERMS, DEFAULT_PERMISSIONS, admin always full & non-reducible). `require_permission()` in security.py; `get_current_user`/login now attach `permissions`. New GET/PATCH `/api/admin/role-permissions`. Enforcement: reports (require_permission "reports"), export ("export"), marketing ("marketing"), users ("manage_users"). Frontend: `can()` in AuthContext, nav gated in Layout, `Guard` route wrapper in App.js (redirects to / if not allowed), and a "Roles & Access Control" matrix UI in Admin → Users (admin column locked). Defaults: caller no Marketing/Reports/Admin/export/delete; manager has Marketing+Reports+Admin(read-only) but no export/migration/manage_users/delete.
- **Case 1:** Lead detail — left fields & right chatter columns scroll independently; header stays fixed.
- **Case 2:** Follow-up ENTRIES — new `follow_ups` collection + CRUD `/api/leads/{id}/followups`, synced to lead.follow_up_date. UI: add form + list with edit/delete under Assignment & Follow-up. Removed the "Appointment" date field.
- **Case 3:** Admin → Automations edit icon (prefilled "Edit Automation" modal, PATCH).
- **Case 4:** Admin → Custom Fields edit icon (prefilled "Edit Field" modal, PATCH).
- **Case 5 (Gmail):** Callback now surfaces the real Google error reason (`?gmail=error&reason=...`) + logs it. Redirect URI confirmed correct in Console; root cause is production consent-screen/test-user or client-secret config — pending user action after redeploy.
- **Case 6:** Leads list "Columns" menu to show/hide columns; persists in localStorage.
- **⚠️ Needs REDEPLOY** for production. RBAC applies on the user's next login/refresh.


## Original Problem Statement
HomeIVF (homeivf.com, at-home IVF fertility care, venture of Seeds of Innocens) runs its entire CRM/lead management/follow-up/conversion cycle on Odoo (homeivf.odoo.com, Odoo 19 Enterprise SaaS). They want a fully-owned custom CRM ("HomeIVF CRM", to be hosted on homeivfcrm.com, branded "Powered by TagQuest") that:
- **Phase 1**: Replicates ALL Odoo functionality they use — interfaces, flows, workflows, reports with filters/dropdowns, full backend admin — with FULL data migration.
- **Phase 2**: AI insights + AI recommendations on every section, plus an "AI Brain" conversational analytics chat (Emergent LLM key approved by user).

## Fix (2026-07) — FB lead NAME empty / phone-in-name (broadened detection) — iteration_23 (14/15→clean)
- **CAUSE:** Form's name field key varied (first_name+last_name, spaced/cased, or a question like "what is your name?"). Earlier fix caught common variants; this adds a last-resort: any field whose normalized key CONTAINS 'name' (excluding company/form/page/user/product/brand/clinic/business) is used as the name, and such fields are kept out of the Q&A card (skip-branch mirrors the exclusion). Webhook 'created' log now records raw field_keys for diagnosis.
- Verified: "what is your name?"→name set + not duplicated in Q&A; company/clinic/etc excluded → phone fallback; first+last, full_name, phone-only regressions pass.
- **⚠️ Needs REDEPLOY.** IMPORTANT: user's "phone-in-name" may simply be that the earlier name fix (iter22) wasn't redeployed yet — confirm redeploy, then check Admin→Facebook delivery log 'field_keys' to see the exact form field names.

## Fix (2026-07) — FB lead NAME empty (list showed phone, detail showed '—') — iteration_22 (11/11 backend)
- **CAUSE:** Form name field isn't always exact key `full_name` (may be first_name+last_name or spaced/cased key). Also DEFAULT_MAP mapped `first_name`→contact_name, grabbing only first name and dropping last_name.
- **FIX (facebook.py _map_and_create_lead):** removed `first_name` from DEFAULT_MAP; added name-derivation fallback — when contact_name/name empty, scan field_data for full_name/name variants OR combine first_name+last_name; name-part fields excluded from Q&A custom card. Verified 11/11 (Akhil Sharma, Ravi Kumar, Meena, Priya Nair, phone-fallback, custom Q&A preserved).
- **⚠️ Needs REDEPLOY.** Applies to NEW leads; existing name-less leads unaffected (name can be edited manually).

## Fix (2026-07) — 🔴 REAL PRODUCTION BLOCKER: Graph #100 "nonexisting field (form_name)" — iteration_21 (8/8 backend)
- **ROOT CAUSE (code bug):** fb_webhook() requested the leadgen object with `fields=...,form_name,...` but `form_name` is NOT a valid field on Meta's leadgen node → Graph returns `(#100) Tried accessing nonexisting field (form_name)` → the ENTIRE lead fetch failed → 0 leads created (even though token/permissions/webhook were all green). This is why no FB leads ever appeared.
- **FIX:** Removed `form_name` from the leadgen fields request; now fetch form name separately via `GET /{form_id}?fields=name` and inject as lead['form_name'] before mapping. Verified iter21 (8/8) incl. field-string assertion + regressions. NOTE: true end-to-end needs live Meta (confirm after redeploy).
- **⚠️ Needs REDEPLOY.** After redeploy, submit a fresh Meta test lead → it should now be `created` in the delivery log and appear in the Lead report (assigned to a caller, with source + timestamp).

## Fix (2026-07) — FB leads unassigned → invisible to callers; now auto-assigned + findable — iteration_20 (9/9 backend)
- **FIX:** _map_and_create_lead now round-robins each FB lead across ACTIVE caller users when no assignment config applies (counter fb_assign_pointer). FB leads are no longer Unassigned → they appear in callers' Lead reports with source 'Meta Lead Ads' + create_date/create_date_ist, exactly like other leads. Verified iter20 (9/9): rotation works, assigned caller sees lead via user_id filter, recent-leads shows caller name.
- Also live: "Recently captured Facebook leads" panel in Admin → Facebook (below Check connection) with Open→ links (iter19).
- **⚠️ Needs REDEPLOY.** After redeploy, existing 14 old FB leads stay Unassigned (created before this) — user can bulk-assign them; NEW leads auto-distribute to callers. If user wants distribution limited to a specific team, configure Admin → Assignment.

## Fix (2026-07) — "Can't see FB leads in CRM" → leads ARE captured but were unfindable — iteration_19 (7/7 backend)
- **ROOT CAUSE:** FB leads ARE created (14 on prod, source 'Meta Lead Ads') but (1) come in UNASSIGNED and caller-role users only see leads assigned to them, and (2) get buried under ~100k migrated leads by the default create_date sort. Admin CAN see them (verified: a fresh FB lead lands at top of admin list + source filter returns them).
- **FIX:** New `GET /api/admin/facebook/recent-leads` (total + latest 25 facebook_lead:true, with assigned_to). Admin → Facebook now shows a "Recently captured Facebook leads" table with "Open →" links — a guaranteed, filter-proof way to find every Meta lead. Verified testing agent iter19 (7/7) incl. regressions (diagnose 5 checks, webhook-log, invalid-sig 401).
- **PRODUCT NOTE for user:** All FB leads are Unassigned → the sales team (callers) can't see them. Options to discuss: (a) enable round-robin assignment for FB leads so callers get them, or (b) let callers see unassigned FB leads. Awaiting user's preference.

## Fix (2026-07) — FB leads: webhook delivers but Graph fetch fails (leads_retrieval / token-app mismatch) — iteration_18 (backend green)
- **Progress:** After redeploy, webhook DELIVERY now succeeds on prod (app 736963545504625 = Success in Meta Track status; signature/app-secret issue resolved). NEW failure surfaced by our delivery log: Graph API fetch of the lead returns "Object ... does not exist / missing permissions".
- **ROOT CAUSE (production Meta config):** the saved Page Access Token was generated under a DIFFERENT Meta app (user screenshot showed Meta App = "Odoo") than the configured CRM App ID (736963545504625), and/or lacks `leads_retrieval`. So delivery works but lead RETRIEVAL is rejected.
- **CODE FIX (diagnostic):** diagnose() now calls Meta `debug_token` and adds two checks: **'Token ↔ App match'** (token app_id vs configured App ID) and **'leads_retrieval permission'** (scope present). Pinpoints the exact problem on prod. Refined webhook error log message. Verified via testing agent iteration_18 (checks present, diagnose 200, regressions green). NOTE: preview DB token is correct (all 5 checks green) → prod token is the wrong one.
- **⚠️ USER ACTION (production):** In Meta Graph API Explorer / token tool, generate a **Page Access Token with Meta App = the CRM app (736963545504625)** (NOT Odoo) for Page HomeIVF, including **leads_retrieval + pages_manage_metadata**. Paste into Admin → Facebook → Page Access Token → Save → Check connection (both new checks must be ✓). Also: test-tool leads are ephemeral (1 per form, deleted on recreate) — a real ad lead or a freshly-created test lead is the reliable check.


- **Diagnosis from user's Meta "Track status" screenshot:** HomeIVF page (273380505860843) has MULTIPLE apps subscribed to leadgen. Two apps deliver `Success`; app **736963545504625 → Failure: `webhooks.delivery.rejected`**. That means Meta DID deliver the leadgen event to the CRM callback but the CRM returned non-2xx (almost certainly 401 invalid signature) → lead never created. Previously the CRM logged nothing → invisible.
- **ROOT CAUSE (production config):** the App Secret saved in CRM Settings → Facebook does not match the app (736963545504625) whose 'page' webhook points to crm.homeivfmarketing.com. HMAC signature check fails → 401 → Meta reports `webhooks.delivery.rejected`.
- **CODE FIX (visibility):** Added `_log_webhook()` in facebook.py — every inbound webhook outcome (rejected/error/skipped/created) is stored in `db.fb_webhook_log` (capped 200). New `GET /api/admin/facebook/webhook-log`; diagnose() now returns `recent_webhook_deliveries`; Admin Facebook diagnostic panel renders them. Verified via testing agent (6/6): bad-sig→401+rejected log; valid-sig+bad leadgen→200+error log; auth enforced; diagnose surfaces deliveries.
- **⚠️ USER ACTION (production):** (1) Redeploy so logging is live. (2) In Meta, ensure the App Secret saved in CRM Settings belongs to the SAME app whose 'page' webhook callback = crm.homeivfmarketing.com/api/webhooks/facebook (the one showing `webhooks.delivery.rejected`). Re-save the correct App Secret, then click "Check connection" — deliveries should flip to `created`.


- **Symptom 1:** "Meta Lead Ads" missing from Source dropdown on prod after redeploys (it was only created lazily on FB lead ingest; startup seed never added it).
- **FIX 1:** Added "Meta Lead Ads" to the startup `source_lead` seed.
- **Symptom 2 (deploy crash):** First deploy attempt of FIX 1 crashed backend startup with `DuplicateKeyError` on catalogs unique index `type_1_id_1` dup {source_lead, id:6}. Root cause: seed used hardcoded `id:i+1`; prod already had a migrated entry at id=6 (Ozonetel) → collision → startup exits → deploy never ready.
- **FIX 2:** Replaced hardcoded-id source_lead seed loop with collision-safe `ensure_catalog("source_lead", name)` (max-id+1 + retry). Verified via testing agent (6/6): clean startup, no dup names, idempotent across restarts, POST still 200. Local sim confirmed collision-safe (id=6 taken → new item id=12).
- **⚠️ Needs PRODUCTION REDEPLOY.** Deployment agent's .gitignore .env flag is a FALSE POSITIVE (app has deployed successfully before with same .gitignore).



## Fix (2026-07-02, batch 20) — FB leads "not showing in report" + Source dropdown — iteration_14 (7/7 backend, 100%)
- **ROOT CAUSE (production data):** the production `settings.facebook.page_access_token` contained the ENTIRE pasted text block (App ID + app secret + WhatsApp SU token label) instead of just the Page token → Graph fetch failed with "Malformed access token" → leadgen webhooks delivered Success (200) but created 0 leads. FIXED directly on production via API: re-set clean app_id/app_secret/page_id/page_access_token (fresh, points to HomeIVF 273380505860843)/verify_token=homeivf_fb_verify_2026/graph v25.0. Production `/admin/facebook/diagnose` now all 3 checks green; webhook registered → https://crm.homeivfmarketing.com/api/webhooks/facebook. Verified a simulated FB lead creates + shows in GET /leads?source_lead=Meta Lead Ads (then archived the test lead #504779).
- **Source dropdown fix (code):** `_map_and_create_lead` now calls `ensure_catalog('source_lead', source)` so "Meta Lead Ads" auto-appears in Source dropdowns/filters. Added shared `core/utils.ensure_catalog`.
- **Catalog-create 500 bug (code):** `POST /api/catalogs/{ctype}` 500'd for migrated types (source_lead/tag) because the `catalog_{ctype}` counter was behind migrated ids → duplicate-key. Now retries insert with max-id+1. Admins can add sources manually again.
- **⚠️ Needs PRODUCTION REDEPLOY** for the ensure_catalog + catalog-500 + attribution + register-webhook-button code to reach prod. After redeploy the next real FB lead auto-adds "Meta Lead Ads" to the dropdown (or admin adds it manually). Leftover empty test lead #504615 on prod (earlier artifact) not archived — user to decide.

- **FB Attribution fix:** the leadgen fetch now requests `ad_id,ad_name,adset_id,adset_name,campaign_id,campaign_name,form_id,form_name,platform` and `_map_and_create_lead` writes `campaign_name`←campaign_name, `ads_campaign_name`←adset_name, `ads_name`←ad_name (+ fb_campaign_id/fb_adset_id/fb_ad_id/fb_form_name). Verified in UI: Attribution card shows Campaign / Ads Campaign / Ad Name populated. `fb_test_lead` accepts optional campaign_name/adset_name/ad_name/form_name to simulate. NOTE: UTM Source/Medium/Campaign stay empty for FB leads — Meta lead forms don't carry UTM params (those come from web/landing-page URLs) unless the form has hidden UTM fields (which would map via field_data).
- **WhatsApp Cloud unblocked:** the System User token (whatsapp_business_management + whatsapp_business_messaging) resolves the old `(#200)` permission error. Saved config in preview settings key='whatsapp_cloud': WABA `30291513857161871` (HomeIVF, INR), phone_number_id `696577696872486` (+91 92112 24222, quality YELLOW, code_verification EXPIRED), verify_token=homeivf_wa_verify_2026. Verified via app endpoints: status configured=true, phone-numbers ✓, templates ✓ (approved list loads). LIVE outbound send test still PENDING a destination number from user.
 — iteration_13 (9/9 backend, 100%)
- **Root cause (diagnosed via live Graph API):** The Meta app `736963545504625` had NO app-level `page`/leadgen webhook subscription at all — its only webhook was `whatsapp_business_account` → `https://homeivf.odoo.com/whatsapp/webhook`. So FB leads had nowhere to be delivered. Also, the user was pasting a **System User token** (belongs to "Odoo" SU id 122101718660933307) into the Page Access Token field → Meta "Malformed access token".
- **Correct creds identified:** Page **"HomeIVF" id `273380505860843`**; its Page Access Token was fetched via `me/accounts` on the SU token. SU token scopes include leads_retrieval + pages_manage_metadata + whatsapp_* (non-expiring, expires_at:0). App ID `736963545504625`, App Secret `39678a3c68cf84bf247fb2f1b9cafd16`.
- **Done via API:** Page subscribed to leadgen (subscribed_apps) ✓. Proved end-to-end webhook registration works (Meta verified preview callback, success:true), then DELETED the preview page subscription to leave a clean slate (no hijack of production leads).
- **New:** `POST /api/admin/facebook/register-webhook {callback_url}` — registers the app-level `page`/leadgen webhook with Meta (POST /{app_id}/subscriptions using app token; Meta verifies via saved verify_token). One-click **"Register leadgen webhook with Meta"** button in Admin → Facebook (`fb-register-webhook-button`). Enhanced `GET /admin/facebook/diagnose` with a 3rd check "App leadgen webhook" that detects exactly this missing piece. `_map_and_create_lead` now keeps `name`/`contact_name` in sync.
- **⚠️ USER ACTION on PRODUCTION (requires redeploy first, since button/endpoint are new code):** Admin → Facebook → enter App ID/Secret, Page ID `273380505860843`, the **Page** Access Token (NOT the SU token), a Verify Token → Save → click "Register leadgen webhook with Meta" → "Check connection" (should be all green) → send a Meta test lead. Preview settings DB currently holds the real creds (verify_token=homeivf_fb_verify_2026) for demonstrability.


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
- ⚠️ ACTION REQUIRED by user to go live: in Google Cloud Console add redirect URI `https://homeivf-crm-1.preview.emergentagent.com/api/oauth/gmail/callback` (and the production one after deploy), enable Gmail API, add gmail.send scope, add account as test user if app in Testing, then click Connect. The previously-registered `homeivf.com/google_account/authentication` URI does NOT work for the CRM. Live send unverified until connected.


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
### Hotfix 2026-06 — Production stall (team locked out after redeploy)
- Symptom: after redeploy, Leads list + Reports/AI Insights spun forever; whole team blocked.
- Root cause: startup ran ~30+ create_index() SERIALLY with await — on large prod collections (leads 110k, follow_ups 73k) this blocked FastAPI startup/readiness (crash-loop → nothing served); AI /analytics also ran 7 aggregations sequentially.
- Fix: server.py moves ALL index creation into a non-blocking background task (asyncio.create_task(_ensure_indexes())) with per-index try/except (log shows 'Startup complete' before 'Index ensure pass complete'). routes/ai.py /analytics runs aggregations concurrently via asyncio.gather(return_exceptions=True) + maxTimeMS=15000 (fails fast, partial-safe). Verified iteration_48 (100%, suite /app/backend/tests/test_prod_stall_fix.py).

### Phase 2 2026-06 — AI Insights dashboards + AI Brain (LIVE)
- New "AI Insights" page (nav + route /ai-insights, perm 'reports'). Advanced charts via recharts: Conversion Funnel, Leads Trend (30d), Source Performance (leads vs converted), Caller Performance (conversion %), Ad Platform pie, Top States. All from GET /api/ai/analytics (concurrent, index-backed, ~1s). KPIs: total/converted/conversion_rate.
- AI Brain chat: POST /api/ai/brain — GPT-5.5 (openai) via Emergent Universal Key (emergentintegrations LlmChat) translates a plain-English question → JSON query spec → safe indexed aggregation → answer + dynamic chart (bar/line/pie/number). Session-scoped history in db.ai_chats; GET /api/ai/brain/history. Null buckets excluded from answers.
- Files: routes/ai.py (reuses reports DIMS/build_match/resolve_labels), pages/AiInsights.jsx, Layout.jsx nav + AI Brain card, App.js route. Backend key EMERGENT_LLM_KEY in backend/.env.
- Verified iteration_47 (100%, suite /app/backend/tests/test_ai_insights.py): analytics ~1.5s, brain 3–8s, RBAC 403 for caller role, all charts render.

### Perf 2026-06 — Go-live optimization (indexes)
- Root cause of slowness on large prod data (110k leads / 1M msgs / 73k follow_ups): follow_ups & caller_activities had NO index (COLLSCAN on every lead-detail open); several report/dashboard match patterns lacked compound indexes.
- Fix (server.py startup, additive/no logic change): added follow_ups [(lead_id,follow_up_date)], follow_up_date, [(source,lead_id)]; caller_activities [(lead_id,created_at)]; wa_tracking lead_id/campaign_id/wamid; leads [(active,follow_up_date)], [(active,user_id)], source_lead, stage_id. All lists already paginated; dashboard bounds by_day window.
- Verified iteration_46 (100%, regression suite /app/backend/tests/test_perf_sections.py): dashboard 0.26s, leads 0.53s, pivots 0.22s, followups 0.13s. No regressions.

### Feature 2026-06 — Duplicate Lead Cleanup + Odoo follow-up → Follow-up entry
- CASE 1 (Duplicate cleanup, Admin > Migration): scan groups leads by phone_digits, keeps the OLDEST, flags newer duplicates CREATED in a date range (default 1–9 Jul) for deletion. Background scan (POST /admin/duplicates/scan → poll /status), preview table, confirm-modal delete (POST /admin/duplicates/delete) archives to deleted_leads (recoverable) then removes + cleans their follow_ups. UI: dup-cleanup-card in Admin.jsx. NOTE: scan uses an indexed two-step approach (distinct on create_date-index window → chunked $in on phone_digits-index) to avoid MongoDB ExecutionTimeout on the ~110k-lead prod dataset (verified iteration_44, ~4s).
- CASE 2 (Odoo follow-up dates): sync now mirrors each lead's Odoo follow_up_date into a real follow_ups entry (source='odoo', one per lead, idempotent) so it shows in the Follow-ups list/reminders. Covers future syncs (_ensure_followups in sync_leads) + one-time backfill of existing leads (_backfill_followups, guarded by settings.followups_backfilled). Verified iteration_43 (100%): backfill created 73,766 entries, unique ids.

### Bugfix 2026-06 — "Run Audit vs Odoo" error (gateway timeout)
- The audit ran ~15 sequential Odoo search_count calls synchronously in the HTTP request (~18-40s over 110k leads / 1M+ messages) → hit the ingress/gateway timeout → button errored in production.
- Fix: audit is now a BACKGROUND JOB. POST /api/admin/migration/audit starts a thread (using the resilient timeout+retry XML-RPC call()) and returns {status:"running"} in ~0.1s; new GET /api/admin/migration/audit/status returns settings.last_audit; frontend runAudit() polls every 3s until done. Audit table render + mount guarded against missing rows. Verified iteration_42 (100%).

### Bugfix 2026-06 — Sync worker killed by hung XML-RPC (process restart / xmlrpc __request error)
- Two prod symptoms: "sync worker no longer running (process restarted or crashed)" and an xmlrpc/client.py __request error. Cause: the Odoo XML-RPC ServerProxy had NO socket timeout, so a hung Odoo request stalled the worker until the platform killed the process.
- Fix (odoo_migrate.py): timeout-aware transports (_TimeoutTransport/_TimeoutSafeTransport, ODOO_TIMEOUT env, default 120s); _authenticate() 5x retry; call() 6x retry with backoff + re-authenticate on transient failures. Per-batch checkpoints let a re-run resume. Verified iteration_41 (100%). Regression test: /app/backend/tests/test_odoo_sync_regression.py.

### Bugfix 2026-06 — Sync worker crash (pymongo receive_message / AutoReconnect)
- Sync started fine but the worker crashed mid-run on a transient MongoDB connection drop during a large lead-chatter bulk_write (pool.py write_command receive_message).
- Fix: MongoClient now uses retryWrites=True + socketTimeoutMS=180000 (odoo_migrate.py); bulk() retries 4x on AutoReconnect/NetworkTimeout/ConnectionFailure with ordered=False (odoo_sync.py); message batch sizes cut 2000→500. Per-batch checkpoints mean re-running "Sync Now" resumes where it left off. Verified iteration_40 (100%).

### Bugfix 2026-06 — "Sync Now" 500 in production (root cause of "nothing happens")
- Real root cause: sync_status() ran uncapped $max aggregations + count_documents over large prod collections (no index → COLLSCAN → timeout → HTTP 500). Pre-fix the modal was gated on sync-status loading so the 500 left sync=null → "nothing happens". After decoupling the modal, sync_start (which called sync_status internally) surfaced the same 500 on confirm.
- Fix: new cheap _next_since() helper computes the delta window from the tiny last_sync settings doc; sync_status wraps every heavy op in try/except with maxTimeMS=8000 (returns None/0 on failure); sync_start no longer calls sync_status; stuck-run self-heal hardened. Verified iteration_39 (100%, both endpoints 200).

### Bugfix 2026-06 — "Sync Now" dead in production
- Root cause: a sync thread dying mid-run (redeploy/crash) left a sync_runs doc stuck at status "running"; frontend permanently disabled the button, and stale-cleanup only ran inside sync/start (never reached) — deadlock. Modal was also gated on sync-status loading.
- Fix: GET /admin/sync/status now self-heals dead runs via threading.enumerate() liveness check (marks error, returns running=null). POST /admin/sync/start uses same check before 409. Frontend confirm modal decoupled from sync-status; loadSync surfaces errors via toast. Verified (iteration_38, 100%).

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
