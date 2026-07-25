# HomeIVF CRM — CHANGELOG

(Newest first. PRD.md holds the static problem statement / architecture; this file grows over time.)

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
