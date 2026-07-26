import asyncio as _asyncio
import os
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import (AutoReconnect, ConnectionFailure, ExecutionTimeout,
                            NetworkTimeout, ServerSelectionTimeoutError,
                            WaitQueueTimeoutError, WTimeoutError)

# TWO connection pools so heavy work can NEVER starve the caller/login path.
#
# The DB server allows ~100 connections; we PARTITION them:
#   • `db`           — INTERACTIVE pool (80): callers' Leads screen, login, lead detail,
#                      activities, agent status. Callers each carry ~5k leads but their
#                      queries are index-scoped (~4–9ms); with a reserved pool they always
#                      get a connection instantly even while admins run heavy reports.
#   • `db_analytics` — HEAVY/BACKGROUND pool (20): dashboards, KPI/trends aggregations,
#                      group-counts, Meta backfill, index builds. If admins hammer reports
#                      or a backfill runs, it can consume at most 20 connections — the 80
#                      interactive connections are untouched, so caller work never stops.
#
# waitQueueTimeoutMS: if the pool is momentarily full, a request FAILS FAST (retryable)
# instead of hanging until the ingress gateway times out and Cloudflare returns 520.
# Per-query .max_time_ms() (in routes) still caps the actual query so a slow scan aborts
# and releases its connection.
_MONGO_URL = os.environ["MONGO_URL"]
_DB_NAME = os.environ["DB_NAME"]


def _strip_csot(url: str) -> str:
    """Remove `timeoutMS` (Client-Side Operation Timeout / CSOT) from the connection URL.

    The platform-managed production connection string injects `timeoutMS=120000`. CSOT is the
    HIGHEST-precedence driver timeout — when present it SUPERSEDES socketTimeoutMS,
    waitQueueTimeoutMS AND every per-query .max_time_ms() we set. So a slow/no-primary op would
    hold its pooled connection for the full 120s instead of aborting in 5–15s → the pool
    exhausts → the 5xx cascade we kept seeing on prod despite all the fast-fail hardening.
    Stripping it lets our explicit timeouts + per-query maxTimeMS actually govern. Credentials
    and every other URL option (appName, retryWrites, w, etc.) are preserved unchanged.
    """
    try:
        p = urlsplit(url)
        if not p.query:
            return url
        kept = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                if k.lower() != "timeoutms"]
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(kept), p.fragment))
    except Exception:
        return url


_MONGO_URL = _strip_csot(_MONGO_URL)

client = AsyncIOMotorClient(
    _MONGO_URL,
    maxPoolSize=80,
    minPoolSize=10,
    maxIdleTimeMS=60000,
    waitQueueTimeoutMS=5000,
    serverSelectionTimeoutMS=8000,
    connectTimeoutMS=10000,
    # Hard cap on how long ANY interactive op may hold its pooled connection. If Atlas is
    # transiently slow, the op aborts at 15s and RELEASES the connection instead of hanging
    # up to 45s — this is what stops a slow DB from cascading into pool exhaustion → the
    # 30s-NetworkTimeout storm on every endpoint. Per-query .max_time_ms() aborts even faster.
    socketTimeoutMS=15000,
    retryReads=True,
    retryWrites=True,
)
db = client[_DB_NAME]

analytics_client = AsyncIOMotorClient(
    _MONGO_URL,
    maxPoolSize=20,
    minPoolSize=2,
    maxIdleTimeMS=60000,
    waitQueueTimeoutMS=8000,
    serverSelectionTimeoutMS=8000,
    connectTimeoutMS=10000,
    socketTimeoutMS=60000,
    retryReads=True,
    retryWrites=True,
)
db_analytics = analytics_client[_DB_NAME]


# Transient / connectivity Mongo errors. When the shared Atlas cluster briefly drops (SSL
# handshake timeout, server-selection timeout, connection storm) pymongo PAUSES the pool and
# every in-flight op raises one of these. These were surfacing as UNCAUGHT HTTP 500s on any
# DB-touching endpoint — most visibly /api/auth/login, whose reads had no error handling. They
# are (a) safe to retry on the read path and (b) at the API boundary should map to 503
# (retryable), never a scary 500. NetworkTimeout/AutoReconnect/ServerSelectionTimeoutError are
# ConnectionFailure subclasses; WaitQueueTimeoutError/ExecutionTimeout/WTimeoutError are not,
# so they are listed explicitly.
TRANSIENT_DB_ERRORS = (
    ConnectionFailure, AutoReconnect, NetworkTimeout, ServerSelectionTimeoutError,
    WaitQueueTimeoutError, ExecutionTimeout, WTimeoutError,
)


async def with_db_retry(op, attempts: int = 3, delay: float = 0.4):
    """Await op() (a zero-arg coroutine factory), retrying transient connectivity errors with a
    short linear backoff so a brief pool-paused window self-heals WITHIN the request instead of
    failing. Use only on idempotent reads (e.g. the login lookup). Re-raises the last error if
    every attempt hits a transient failure, so the global handler can still turn it into a 503."""
    last = None
    for i in range(attempts):
        try:
            return await op()
        except TRANSIENT_DB_ERRORS as e:
            last = e
            if i < attempts - 1:
                await _asyncio.sleep(delay * (i + 1))
    raise last
