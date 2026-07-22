import os
from motor.motor_asyncio import AsyncIOMotorClient

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

client = AsyncIOMotorClient(
    _MONGO_URL,
    maxPoolSize=80,
    minPoolSize=10,
    maxIdleTimeMS=60000,
    waitQueueTimeoutMS=5000,
    serverSelectionTimeoutMS=8000,
    connectTimeoutMS=10000,
    socketTimeoutMS=45000,
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
