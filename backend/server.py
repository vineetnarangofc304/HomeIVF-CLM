import os

from dotenv import load_dotenv

load_dotenv()

import logging
import asyncio
import re
import time as _time
import traceback as _traceback
from datetime import datetime, timezone

import jwt as _jwt
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from core.db import db, db_analytics, TRANSIENT_DB_ERRORS
from core.security import hash_password, verify_password, get_jwt_secret
from core.utils import now_utc_str, to_ist_str, ensure_catalog
from routes import admin as admin_routes
from routes import auth as auth_routes
from routes import calls as call_routes
from routes import facebook as facebook_routes
from routes import wa_cloud as wa_cloud_routes
from routes import agent as agent_routes
from routes import catalogs as catalog_routes
from routes import attachments as attachment_routes
from routes import export as export_routes
from routes import marketing as marketing_routes
from routes import ai as ai_routes
from routes import gmail as gmail_routes
from routes import chatter as chatter_routes
from routes import filters as filter_routes
from routes import leads as lead_routes
from routes import reports as report_routes
from routes import templates as template_routes
from routes import users as user_routes
from routes import webhooks as webhook_routes
from routes import whatsapp as whatsapp_routes
from routes import wa_tracking as wa_tracking_routes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="HomeIVF CRM API")


@app.exception_handler(PyMongoError)
async def _db_error_handler(request: Request, exc: PyMongoError):
    """App-wide safety net for Mongo failures. When the (shared) Atlas cluster is briefly
    unreachable/saturated, pymongo raises connectivity errors that were previously UNCAUGHT on
    endpoints without a local try/except — most visibly /api/auth/login — surfacing to users as
    HTTP 500. Map the transient/connectivity ones to 503 + Retry-After (so clients back off and
    retry instead of treating it as a hard server bug); anything else stays a clean 500."""
    if isinstance(exc, TRANSIENT_DB_ERRORS):
        logger.warning("Transient DB error on %s %s: %s: %s",
                       request.method, request.url.path, type(exc).__name__, exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "Service is temporarily busy. Please try again in a moment."},
            headers={"Retry-After": "2"},
        )
    logger.error("Unhandled DB error on %s %s: %s: %s",
                 request.method, request.url.path, type(exc).__name__, exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# ---- Lightweight request logger: capture 5xx + slow requests to `error_logs` so the exact
# failing endpoint is visible from inside the app (Admin → System Health) without DevTools.
# Registered BEFORE CORS so CORS stays the outermost middleware. Logging is fire-and-forget
# (create_task) so it never adds latency, and is fully wrapped in try/except so it can never
# itself cause a failure.
_SLOW_MS = 8000
_SKIP_LOG_PATHS = {"/api/health", "/api/admin/error-logs", "/api/admin/error-logs/summary"}
# HARD safety limits so this DIAGNOSTIC can never amplify an incident. Under a 5xx storm the
# naive version spawned one unbounded background DB insert per failing request — into an
# already-saturated pool — piling up tasks/connections until the worker died (empty origin
# response → Cloudflare 520). We now (a) cap concurrent log writes and shed the rest, and
# (b) hard-timeout each write so it releases its connection fast instead of hanging.
_log_inflight = 0
_LOG_MAX_INFLIGHT = 5
_LOG_WRITE_TIMEOUT = 1.5


async def _record_issue(method, path, query, status, dur_ms, uid, err_type, err_msg, tb):
    global _log_inflight
    if _log_inflight >= _LOG_MAX_INFLIGHT:
        return  # load-shed: diagnostics must NEVER add pressure during a storm
    _log_inflight += 1
    try:
        now = now_utc_str()
        await asyncio.wait_for(db.error_logs.insert_one({
            "created_dt": datetime.now(timezone.utc),  # BSON date → TTL auto-purge (7 days)
            "ts": now, "ts_ist": to_ist_str(now),
            "kind": "error" if (status or 0) >= 500 else "slow",
            "method": method, "path": path, "query": (query or "")[:300],
            "status": status, "duration_ms": int(dur_ms), "user_id": uid,
            "error_type": err_type, "error": (err_msg or "")[:600], "traceback": (tb or "")[:4000],
        }), timeout=_LOG_WRITE_TIMEOUT)
    except Exception:
        pass
    finally:
        _log_inflight -= 1


def _uid_from_scope(scope):
    try:
        for k, v in scope.get("headers", []):
            if k == b"authorization":
                auth = v.decode()
                if auth.startswith("Bearer "):
                    payload = _jwt.decode(auth[7:], get_jwt_secret(), algorithms=["HS256"])
                    return int(payload["sub"]) if payload.get("sub") else None
    except Exception:
        return None
    return None


class RequestLogMiddleware:
    """Pure-ASGI logger — it ONLY observes the response status via the `send` stream and never
    buffers/rewrites the body, so (unlike BaseHTTPMiddleware) it cannot produce empty/malformed
    responses or add latency. Captures 5xx + slow requests into `error_logs` for Admin → System
    Health, with the load-shedding guards above so it can never amplify an incident."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        method = scope.get("method", "")
        path = scope.get("path", "")
        if method == "OPTIONS" or path in _SKIP_LOG_PATHS:
            return await self.app(scope, receive, send)
        start = _time.monotonic()
        status = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message.get("status", 500)
            await send(message)

        query = (scope.get("query_string") or b"").decode("latin-1")[:300]
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            dur = (_time.monotonic() - start) * 1000
            if _log_inflight < _LOG_MAX_INFLIGHT:
                asyncio.create_task(_record_issue(
                    method, path, query, 500, dur, _uid_from_scope(scope),
                    type(e).__name__, str(e), _traceback.format_exc()))
            raise
        dur = (_time.monotonic() - start) * 1000
        if (status["code"] >= 500 or dur >= _SLOW_MS) and _log_inflight < _LOG_MAX_INFLIGHT:
            asyncio.create_task(_record_issue(
                method, path, query, status["code"], dur, _uid_from_scope(scope), None, None, None))


# NOTE: add_middleware prepends → the LAST added is OUTERMOST. Add the logger first, then CORS,
# so CORS stays outermost and every response (incl. errors) still gets CORS headers.
app.add_middleware(RequestLogMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import APIRouter

api = APIRouter(prefix="/api")
api.include_router(auth_routes.router)
api.include_router(user_routes.router)
api.include_router(lead_routes.router)
api.include_router(chatter_routes.router)
api.include_router(catalog_routes.router)
api.include_router(template_routes.router)
api.include_router(whatsapp_routes.router)
api.include_router(report_routes.router)
api.include_router(webhook_routes.router)
api.include_router(filter_routes.router)
api.include_router(admin_routes.router)
api.include_router(call_routes.router)
api.include_router(facebook_routes.router)
api.include_router(wa_cloud_routes.router)
api.include_router(agent_routes.router)
api.include_router(attachment_routes.router)
api.include_router(export_routes.router)
api.include_router(marketing_routes.router)
api.include_router(ai_routes.router)
api.include_router(gmail_routes.router)
api.include_router(wa_tracking_routes.router)


@api.get("/health")
async def health():
    return {"status": "ok", "service": "HomeIVF CRM API", "powered_by": "TifTech"}


app.include_router(api)

DEFAULT_LEAD_STAGES = ["Contact Attempt", "Contacted", "Converted", "Closed"]
DEFAULT_FOLLOW_UP_TAGS = ["Follow UP 1", "Follow UP 2", "Follow UP 3", "Follow UP 4", "Follow UP 5"]


INDEX_SPECS = [
    ("users", "email", {"unique": True}),
    ("users", "id", {"unique": True}),
    ("login_attempts", "identifier", {}),
    ("leads", "id", {"unique": True}),
    ("leads", [("create_date", -1)], {}),
    ("leads", [("create_date_ist", -1)], {}),
    ("leads", [("write_date", -1)], {}),
    ("leads", "user_id", {}),
    ("leads", "tags", {}),
    ("leads", "lead_stage", {}),
    ("leads", "phone_digits", {}),
    # Meta backfill de-dupes by facebook_leadgen_id (find_one per fetched lead). Without an
    # index that is a full ~120k collscan PER lead → holds DB connections / pool-exhaustion
    # risk during a recovery run. Sparse: only Facebook leads carry this field.
    ("leads", "facebook_leadgen_id", {"sparse": True}),
    ("leads", "follow_up_date", {}),
    ("leads", "active", {}),
    ("leads", [("active", 1), ("create_date", -1)], {}),
    ("leads", [("active", 1), ("create_date_ist", -1)], {}),
    ("leads", [("active", 1), ("lead_stage", 1)], {}),
    ("leads", [("active", 1), ("follow_up_date", 1)], {}),
    ("leads", [("active", 1), ("user_id", 1)], {}),
    ("leads", "source_lead", {}),
    ("leads", "stage_id", {}),
    # Sort-covering compound indexes for the /leads list. The list sorts by
    # [(sort_field, dir), ("id", -1)]; without "id" in the index Mongo does a BLOCKING
    # in-memory SORT of every matching doc (~100k for admin) which is slow and, past the
    # 32MB sort limit, errors with "Sort exceeded memory limit" → the page timed out /
    # "Request failed". These cover the default (create_date) list for admin & callers.
    ("leads", [("active", 1), ("create_date", -1), ("id", -1)], {}),
    ("leads", [("active", 1), ("user_id", 1), ("create_date", -1), ("id", -1)], {}),
    # "Lead in Pipeline" tab (default) filters pipeline!=False. This index covers that
    # filter + the [create_date,id] sort so the tab never blocking-sorts / 500s at scale.
    ("leads", [("active", 1), ("pipeline", 1), ("create_date", -1), ("id", -1)], {}),
    # Caller-scoped "Lead in Pipeline" tab (user_id + pipeline + sort) — keeps a caller's
    # default view index-covered even when they have thousands of raw Ozonetel leads mixed
    # in (was a possible blocking fetch → the caller-side 500 under concurrent load).
    ("leads", [("active", 1), ("user_id", 1), ("pipeline", 1), ("create_date", -1), ("id", -1)], {}),
    # The list sorts by [(sort_field, dir), ("id", -1)]. For non-create_date sorts
    # (Name / City / Phone / Updated column headers) without a matching compound index,
    # Mongo does a BLOCKING in-memory sort of the whole filtered set (up to 100k+ docs) →
    # the request hangs long enough for the ingress gateway to return 503. These make
    # every sortable column index-backed so it can't hang.
    ("leads", [("active", 1), ("write_date", -1), ("id", -1)], {}),
    ("leads", [("active", 1), ("contact_name", 1), ("id", -1)], {}),
    ("leads", [("active", 1), ("name", 1), ("id", -1)], {}),
    ("leads", [("active", 1), ("city", 1), ("id", -1)], {}),
    ("leads", [("active", 1), ("phone", 1), ("id", -1)], {}),
    ("leads", [("active", 1), ("lead_stage", 1), ("id", -1)], {}),
    ("leads", [("active", 1), ("follow_up_date", 1), ("id", -1)], {}),
    ("leads", [("active", 1), ("source_lead", 1), ("id", -1)], {}),
    # Common list FILTERS that otherwise scan the collection before sorting.
    ("leads", [("active", 1), ("source_lead", 1), ("create_date", -1), ("id", -1)], {}),
    ("leads", [("active", 1), ("lead_stage", 1), ("create_date", -1), ("id", -1)], {}),
    # Lead-stage + TAGS filter (e.g. the "Contacted + OPD Booked" view). `tags` is MULTIKEY;
    # without an index that carries tags BEFORE create_date the planner picks the plain `tags`
    # index and does a BLOCKING in-memory SORT of the whole tag set by create_date → 18s → 504
    # → the /api/leads connection-pool-exhaustion cascade. With this index a single-tag $in
    # scans in create_date order (no sort) and a multi-tag $in uses an efficient SORT_MERGE,
    # examining ~limit keys instead of fetching the entire ~24k lead_stage bucket.
    ("leads", [("active", 1), ("lead_stage", 1), ("tags", 1), ("create_date", -1), ("id", -1)], {}),
    ("leads", [("active", 1), ("follow_up_tag", 1)], {}),
    ("leads", [("active", 1), ("priority", 1)], {}),
    # Prefix ('starts with') search on name fields uses these single-field indexes
    # instead of a full collection scan (the "search is slow" fix).
    ("leads", "name", {}),
    ("leads", "contact_name", {}),
    ("leads", "email_from", {}),
    # Lowercased search fields — a CASE-SENSITIVE '^prefix' regex on these uses tight
    # index bounds (case-insensitive regex on the raw fields could not, so every search
    # scanned all ~120k docs → connection-pool exhaustion → intermittent 500s on login).
    ("leads", "name_lc", {}),
    ("leads", "contact_name_lc", {}),
    ("leads", "email_lc", {}),
    # Covering indexes so the report aggregations run index-only (docs=0) instead of
    # paging the whole ~240MB collection off disk: trends (period+stage), dashboard
    # date-range panels, and the dow/hour heatmap.
    ("leads", [("create_date_ist", -1), ("lead_stage", 1)], {}),
    ("leads", [("active", 1), ("create_date_ist", -1), ("lead_stage", 1)], {}),
    ("leads", [("create_date_ist", -1), ("create_dow", 1), ("create_hour", 1)], {}),
    # Dashboard/KPI scope (base = active + pipeline!=False, grouped by lead_stage over a
    # create_date_ist range): index-first so cold (uncached) report loads never page the
    # whole ~240MB collection. Admin scope + caller (user_id) scope.
    ("leads", [("active", 1), ("pipeline", 1), ("create_date_ist", -1), ("lead_stage", 1)], {}),
    ("leads", [("active", 1), ("user_id", 1), ("pipeline", 1), ("create_date_ist", -1)], {}),
    # Sort-by-column coverage for the Leads grid. Without these, clicking the "Assigned To"
    # (user_id) or "Follow-up date" column headers does a BLOCKING SORT over the ~120k pipeline
    # docs. maxTimeMS does NOT reliably interrupt a large blocking sort, so on production those
    # sorts ran 2-6 minutes and 504'd (holding connections). With these, the sort is served by
    # an index walk (IXSCAN+LIMIT, ~4ms). Mirrors the existing per-column sort indexes above.
    ("leads", [("active", 1), ("user_id", 1), ("id", -1)], {}),
    ("leads", [("active", 1), ("user_id", -1), ("id", -1)], {}),
    ("leads", [("active", 1), ("user_id", 1), ("create_date", -1), ("id", -1)], {}),
    ("leads", [("active", 1), ("follow_up_date", -1), ("id", -1)], {}),
    # Reverse-direction coverage for the remaining UI-sortable Leads columns. Each grid column
    # header toggles asc<->desc; the existing indexes above only covered ONE direction, so the
    # other direction did a blocking sort over ~120k docs (the user_id/follow_up_date 504s). These
    # make BOTH directions of every clickable column an index walk (~4ms). (Non-UI, API-only sort
    # columns are intentionally not indexed here to stay well under Mongo's 64-index cap; the
    # list_leads wall-clock guard below makes those fail fast instead of hanging.)
    ("leads", [("active", 1), ("create_date", 1), ("id", -1)], {}),
    ("leads", [("active", 1), ("contact_name", -1), ("id", -1)], {}),
    ("leads", [("active", 1), ("phone", -1), ("id", -1)], {}),
    ("leads", [("active", 1), ("lead_stage", -1), ("id", -1)], {}),
    ("leads", [("active", 1), ("source_lead", -1), ("id", -1)], {}),
    ("follow_ups", [("lead_id", 1), ("follow_up_date", -1)], {}),
    ("follow_ups", [("follow_up_date", 1)], {}),
    ("follow_ups", [("source", 1), ("lead_id", 1)], {}),
    # Owner-scoped reminder poll (Case 2) — only the follow-up's creator is reminded.
    ("follow_ups", [("created_by", 1), ("follow_up_date", 1)], {}),
    ("caller_activities", [("lead_id", 1), ("created_at", -1)], {}),
    ("wa_tracking", "lead_id", {}),
    ("wa_tracking", "campaign_id", {}),
    ("wa_tracking", "wamid", {}),
    ("messages", [("lead_id", 1), ("date", -1)], {}),
    ("messages", "id", {}),
    ("wa_messages", [("channel_id", 1), ("date", -1)], {}),
    ("wa_channels", "id", {"unique": True}),
    ("wa_channels", "phone_digits", {}),
    ("wa_channels", [("last_message_date", -1)], {}),
    # Case 1 — caller chat-visibility filter (channels owned by the assigned caller).
    ("wa_channels", [("owner_id", 1), ("last_message_date", -1)], {}),
    # unread-summary poll ($match unread_count>0, +owner_id for callers) was a
    # full wa_channels scan every 15s per agent; these make it index-supported.
    ("wa_channels", [("unread_count", 1)], {}),
    ("wa_channels", [("owner_id", 1), ("unread_count", 1)], {}),
    ("activities", [("user_id", 1), ("state", 1), ("date_deadline", 1)], {}),
    ("catalogs", [("type", 1), ("id", 1)], {"unique": True}),
    ("contacts", "id", {"unique": True}),
    ("webhooks", "token", {}),
    ("call_events", "id", {"unique": True}),
    ("call_events", [("created_at", -1)], {}),
    ("call_events", "ucid", {}),
    ("call_events", "lead_id", {}),
    ("call_events", "user_id", {}),
    # Case 2 — presence/attendance collections were UNINDEXED, so every status change,
    # /agent/live poll, attendance query and the daily reset ran a full collscan on a
    # growing status_logs collection → connection-pool exhaustion → 30s-timeout 500s on
    # login and all DB-touching endpoints. These make every status_logs access index-first.
    ("status_logs", [("user_id", 1), ("end", 1)], {}),
    ("status_logs", [("end", 1)], {}),
    ("status_logs", [("date", 1)], {}),
    ("status_logs", [("user_id", 1), ("start", -1)], {}),
    ("lead_queue", [("lead_id", 1)], {}),
    # Server-side request logging (Admin → System Health). TTL auto-purges after 7 days so the
    # collection stays tiny; secondary indexes make the recent-list + summary queries fast.
    ("error_logs", "created_dt", {"expireAfterSeconds": 604800}),
    ("error_logs", [("ts", -1)], {}),
    ("error_logs", [("kind", 1), ("ts", -1)], {}),
    ("error_logs", [("status", 1), ("ts", -1)], {}),
]


async def _ensure_indexes():
    """Build indexes in the background so a slow/large-collection build never blocks
    startup (which previously stalled the whole app on production). Each build is
    isolated: one failure (e.g. a duplicate-key on a unique index) won't abort the rest."""
    # Run this entire heavy startup routine (index builds + one-time 120k backfills) on the
    # ANALYTICS pool so it never consumes the interactive connections callers/login need.
    db = db_analytics
    for coll, keys, kwargs in INDEX_SPECS:
        try:
            await db[coll].create_index(keys, **kwargs)
        except Exception as e:
            logger.warning(f"index {coll}.{keys} skipped: {str(e)[:120]}")
    # One-time (idempotent) backfill of precomputed date-parts so the heatmap / trends
    # aggregations are index-COVERED. Only touches leads still missing the field, so it
    # is a no-op on every later startup. Runs in this background task (never blocks
    # readiness); the heatmap has an $ifNull fallback so it stays correct meanwhile.
    try:
        res = await db.leads.update_many(
            {"create_dow": {"$exists": False}},
            [
                {"$set": {"create_dt": {"$dateFromString": {
                    "dateString": "$create_date_ist", "format": "%Y-%m-%d %H:%M:%S", "onError": None}}}},
                {"$set": {"create_dow": {"$dayOfWeek": "$create_dt"}, "create_hour": {"$hour": "$create_dt"}}},
            ],
        )
        if res.modified_count:
            logger.info(f"Backfilled date-parts on {res.modified_count} leads")
    except Exception as e:
        logger.warning(f"date-parts backfill skipped: {str(e)[:160]}")
    # One-time (idempotent) backfill: mark raw (un-promoted) Ozonetel leads pipeline=False
    # so the "Lead in Pipeline" tab ({pipeline:{$ne:False}}) can use its indexed, sort-
    # covering plan. Touches only the SMALL raw-Ozonetel subset, so it's fast & low-risk;
    # everything else is left field-less (still matches $ne:False → no vanish window).
    try:
        res = await db.leads.update_many(
            {"ozonetel_lead": True, "in_pipeline": {"$ne": True}, "pipeline": {"$exists": False}},
            {"$set": {"pipeline": False}},
        )
        if res.modified_count:
            logger.info(f"Backfilled pipeline=False on {res.modified_count} raw Ozonetel leads")
    except Exception as e:
        logger.warning(f"pipeline backfill skipped: {str(e)[:160]}")
    # One-time (idempotent) backfill of lowercased search fields (name_lc/contact_name_lc/
    # email_lc). Case-sensitive '^prefix' search on these uses tight index bounds; the old
    # case-insensitive regex on the raw fields scanned all ~120k docs per search and
    # exhausted the connection pool (→ intermittent 500s on login). Only touches docs still
    # missing name_lc, so it is a no-op on every later startup.
    try:
        res = await db.leads.update_many(
            {"name_lc": {"$exists": False}},
            [{"$set": {
                "name_lc": {"$toLower": {"$ifNull": ["$name", ""]}},
                "contact_name_lc": {"$toLower": {"$ifNull": ["$contact_name", ""]}},
                "email_lc": {"$toLower": {"$ifNull": ["$email_from", ""]}},
            }}],
        )
        if res.modified_count:
            logger.info(f"Backfilled search fields on {res.modified_count} leads")
    except Exception as e:
        logger.warning(f"search-field backfill skipped: {str(e)[:160]}")
    # Case 1 — backfill wa_channels.owner_id from the assigned caller of the matching lead
    # (by phone number). Idempotent: only channels still missing owner_id. New channels get
    # it at creation and lead reassignment keeps it in sync going forward.
    try:
        if await db.wa_channels.count_documents({"owner_id": {"$exists": False}}) > 0:
            phone_owner = {}
            async for l in db.leads.find(
                {"phone_digits": {"$nin": [None, ""]}, "user_id": {"$ne": None}},
                {"_id": 0, "phone_digits": 1, "user_id": 1}):
                pd = (l.get("phone_digits") or "")[-10:]
                if pd:
                    phone_owner[pd] = l.get("user_id")
            from pymongo import UpdateOne
            ops, n = [], 0
            async for ch in db.wa_channels.find({"owner_id": {"$exists": False}}, {"_id": 0, "id": 1, "phone_digits": 1}):
                pd = re.sub(r"\D", "", ch.get("phone_digits") or "")[-10:]
                ops.append(UpdateOne({"id": ch["id"]}, {"$set": {"owner_id": phone_owner.get(pd)}}))
                if len(ops) >= 1000:
                    await db.wa_channels.bulk_write(ops, ordered=False); n += len(ops); ops = []
            if ops:
                await db.wa_channels.bulk_write(ops, ordered=False); n += len(ops)
            if n:
                logger.info(f"Backfilled owner_id on {n} WhatsApp channels")
    except Exception as e:
        logger.warning(f"channel owner backfill skipped: {str(e)[:160]}")
    logger.info("Index ensure pass complete")


async def _status_reset_loop():
    """Case 2 (choice 3a) — reset everyone to Offline at the start of each IST day.
    Runs immediately on startup (covers overnight/deploy rollovers), then every 5 min so
    the day-boundary reset lands within a few minutes of IST midnight. Idempotent per day."""
    from core.utils import reset_stale_statuses
    while True:
        try:
            n = await reset_stale_statuses()
            if n:
                logger.info(f"Daily status reset — {n} user(s) set Offline")
        except Exception as e:
            logger.error(f"status reset failed: {str(e)[:150]}")
        await asyncio.sleep(300)


@app.on_event("startup")
async def startup():
    # Enlarge the default thread pool. bcrypt (login / password verify) is CPU-bound (~250ms)
    # and is offloaded via asyncio.to_thread → the DEFAULT executor (only ~min(32,cpu+4) threads).
    # At the morning rush 24 callers log in near-simultaneously; with too few threads the bcrypt
    # calls queue and stall the whole worker. A larger pool lets them run concurrently (bcrypt
    # releases the GIL) so logins don't pile up into gateway-timeout 500s.
    import concurrent.futures
    try:
        asyncio.get_running_loop().set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=48, thread_name_prefix="pool"))
    except Exception as e:
        logger.error(f"executor setup failed: {e}")
    try:
        from core.storage import init_storage
        await init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
    # Build indexes in the background — never block startup / readiness on this.
    asyncio.create_task(_ensure_indexes())
    # Daily Offline reset (Case 2) — background loop.
    asyncio.create_task(_status_reset_loop())
    # Seed admin
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        await db.users.insert_one({
            "id": 1, "email": admin_email, "name": "HomeIVF Admin", "role": "admin",
            "active": True, "password_hash": hash_password(admin_password),
            "created_at": now_utc_str(),
        })
        logger.info("Seeded admin user")
    elif not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}})

    # Counter floor for new user ids / lead ids (above imported id ranges)
    await db.counters.update_one({"_id": "user"}, {"$max": {"seq": 1000}}, upsert=True)
    await db.counters.update_one({"_id": "lead"}, {"$max": {"seq": 500000}}, upsert=True)
    await db.counters.update_one({"_id": "message"}, {"$max": {"seq": 5000000}}, upsert=True)
    await db.counters.update_one({"_id": "wa_message"}, {"$max": {"seq": 5000000}}, upsert=True)
    await db.counters.update_one({"_id": "activity"}, {"$max": {"seq": 1000}}, upsert=True)
    await db.counters.update_one({"_id": "call"}, {"$max": {"seq": 1}}, upsert=True)
    await db.status_logs.create_index([("user_id", 1), ("start", -1)])
    await db.status_logs.create_index("date")

    # Seed default lead stages / follow-up tags
    for i, name in enumerate(DEFAULT_LEAD_STAGES):
        await db.catalogs.update_one(
            {"type": "lead_stage", "name": name},
            {"$setOnInsert": {"id": i + 1, "type": "lead_stage", "name": name, "sequence": i + 1, "active": True}},
            upsert=True,
        )
    for i, name in enumerate(DEFAULT_FOLLOW_UP_TAGS):
        await db.catalogs.update_one(
            {"type": "follow_up_tag", "name": name},
            {"$setOnInsert": {"id": i + 1, "type": "follow_up_tag", "name": name, "sequence": i + 1, "active": True}},
            upsert=True,
        )
    # Seed follow-up status values (Case 5 — dynamic, admin-editable). "Not Done" was
    # removed per Case 2; deactivate any legacy "Not Done" catalog entry.
    for i, name in enumerate(["Completed", "Rescheduled", "Cancelled"]):
        await db.catalogs.update_one(
            {"type": "followup_status", "name": name},
            {"$setOnInsert": {"id": i + 1, "type": "followup_status", "name": name, "sequence": i + 1, "active": True}},
            upsert=True,
        )
    await db.catalogs.update_one({"type": "followup_status", "name": "Not Done"}, {"$set": {"active": False}})
    await db.counters.update_one({"_id": "catalog_followup_status"}, {"$max": {"seq": 5}}, upsert=True)
    # Seed default source_lead values (collision-safe: ensure_catalog computes max-id+1,
    # so it never clashes with migrated catalog ids)
    for name in ["landing_page", "chatbot", "website", "App", "Callback_Request", "Meta Lead Ads", "Website AI Agent"]:
        await ensure_catalog("source_lead", name)
    # Seed Indian states + countries (Case 1 dropdowns)
    if await db.catalogs.count_documents({"type": "state"}) == 0:
        states = ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
                  "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
                  "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
                  "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
                  "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
                  "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh",
                  "Lakshadweep", "Puducherry"]
        await db.catalogs.insert_many([
            {"id": i + 1, "type": "state", "name": n, "sequence": i + 1, "active": True}
            for i, n in enumerate(states)])
        await db.counters.update_one({"_id": "catalog_state"}, {"$max": {"seq": len(states) + 1}}, upsert=True)
    if await db.catalogs.count_documents({"type": "country"}) == 0:
        countries = ["India", "Nepal", "Bangladesh", "Sri Lanka", "United Arab Emirates", "Saudi Arabia",
                     "Qatar", "Oman", "Kuwait", "Bahrain", "United States", "United Kingdom", "Canada",
                     "Australia", "Singapore", "Malaysia", "Germany", "France", "Other"]
        await db.catalogs.insert_many([
            {"id": i + 1, "type": "country", "name": n, "sequence": i + 1, "active": True}
            for i, n in enumerate(countries)])
        await db.counters.update_one({"_id": "catalog_country"}, {"$max": {"seq": len(countries) + 1}}, upsert=True)
    # Seed the Disposition Tag → Lead Stage mapping (Case 3). Only if not already set, so
    # an admin's later edits in the Admin panel are never overwritten on restart.
    if await db.settings.find_one({"key": "disposition_map"}) is None:
        disp_map = {
            "Contact Attempt": ["Busy", "Not Reachable", "Phone Switched Off", "Ringing"],
            "Contacted": ["Call back for first pitch", "Call back for appointment", "OPD Booked"],
            "Converted": ["OPD Done", "Registration Done"],
            "Closed": ["Age Issue", "Already Have Kid", "Already Pregnant", "Clinic Not Available",
                       "Gender Selection", "Incoming Not Available", "Invalid Number", "Job Enquiry",
                       "Junk", "Language Barrier", "Not Contactable", "Not Interested (Fund Issue)",
                       "Not Interested (Competition)", "Not Looking for Treatment", "Relative Related Enquiry",
                       "Sperm/Egg Donor", "Unmarried", "Valid Not Interested", "Wrong Number",
                       "Abusive Language", "Not Eligible For Treatment"],
        }
        for tags in disp_map.values():
            for t in tags:
                await ensure_catalog("tag", t)
        await db.settings.update_one({"key": "disposition_map"}, {"$set": {"map": disp_map}}, upsert=True)
        logger.info("Seeded disposition tag→stage mapping")
    logger.info("Startup complete")
