import os
from motor.motor_asyncio import AsyncIOMotorClient

# Resilience settings (prevents the "slow query → everything 503s" cascade):
# - Bigger pool for 24+ concurrent callers each firing several parallel requests on load.
# - serverSelectionTimeoutMS: fail fast (don't hang 30s) if the DB is briefly unreachable.
# - socketTimeoutMS caps a single stuck socket; per-query .max_time_ms() (see routes) caps
#   the actual query so a slow scan aborts and RELEASES its pooled connection instead of
#   holding it until the ingress gateway times out (503).
client = AsyncIOMotorClient(
    os.environ["MONGO_URL"],
    maxPoolSize=100,
    minPoolSize=10,
    maxIdleTimeMS=60000,
    serverSelectionTimeoutMS=8000,
    connectTimeoutMS=10000,
    socketTimeoutMS=45000,
    retryReads=True,
    retryWrites=True,
)
db = client[os.environ["DB_NAME"]]
