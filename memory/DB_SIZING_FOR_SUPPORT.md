# HomeIVF CRM — URGENT Production DB Incident + Tier Upgrade (copy-paste email for Emergent Support)

> Send to: support@emergent.sh — Subject: "URGENT: HomeIVF CRM production DB — ReplicaSetNoPrimary + capacity upgrade to M30"

---

Hi Emergent Support,

Our production CRM is currently degraded/unusable because the managed MongoDB Atlas cluster
has **no healthy primary** (replica-set failover event), causing request pile-up and 5xx across
the app. Please treat this as an active production incident.

**App details**
- App name: **HomeIVF CRM**
- Production URL: **https://hi-connect-1687.emergent.host** (custom domain: crm.homeivfmarketing.com)
- Job ID: <PASTE YOUR JOB ID HERE>
- DB cluster (managed): **customer-apps-*.o9d3cj.mongodb.net**

**What we're seeing (with evidence)**
- Our in-app DB health probe flaps: on manual refresh it succeeds in **~2 ms** ("Database reachable"),
  then within seconds returns **"Database unreachable"** again. The intermittent 2 ms success proves
  the nodes are network-reachable and credentials are correct — the problem is a **missing/flapping primary**.
- MongoDB topology in our logs: **ReplicaSetNoPrimary**
  - `customer-apps-shard-00-00` → RSSecondary (up)
  - `customer-apps-shard-00-01` → **SSL handshake timed out** (Unknown)
  - `customer-apps-shard-00-02` → **connection refused [Errno 111]** (Unknown)
- Because there is no primary, all primary-requiring ops wait, exhausting the connection pool
  (`WaitQueueTimeoutError ... maxPoolSize: 80`), and every endpoint eventually 5xx's.
- System Health (last 24h): **~779 errors, ~8,400 slow requests**; top failing endpoint `/api/leads`.
- Incident window observed: **~13:58–16:37 IST, 26 Jul 2026**, and ongoing.

**We need — three things**
1. **Restore the cluster primary / complete failover NOW.** Two of three replica-set members are
   down (one refusing connections, one failing SSL handshake). Please bring them back so an election
   can promote a primary. This is the immediate outage fix.
2. **This app is confirmed STILL on the shared cluster** (`customer-apps.o9d3cj.mongodb.net`, no
   dedicated migration has gone through). Please **migrate it to a dedicated cluster at M30**
   (auto-scaling M30→M40). A shared cluster cannot serve 120k+ leads + 24 concurrent callers +
   ~650 writes/day.
3. **Please review the injected `timeoutMS=120000` in our connection string.** That platform-set
   Client-Side Operation Timeout (120s) was overriding our application's fast-fail timeouts and
   per-query limits, so a slow op held its pooled connection for 2 minutes → pool exhaustion. We
   have worked around it in code (we strip `timeoutMS` before building the client), but please
   confirm whether a 120s CSOT is intended for shared-cluster apps — a much lower value (or none)
   is far safer.


**Our workload (why M30)**
- **120,000+ leads** and growing (~**650 new Meta leads/day** + continuous call/activity/status writes).
- **24 callers working concurrently** + admins/managers running dashboards & reports.
- This is a connection- and write-heavy workload; M30 (~8 GB RAM) keeps the working set + indexes
  resident and avoids the CPU/IOPS throttling of burstable tiers.

**What we've already done in application code (so you can rule the app out)**
- Single Mongo client per process; **two bounded pools** (interactive 80 / analytics 20) — no
  per-request client creation.
- Fast-fail everywhere: `serverSelectionTimeoutMS=8000`, `waitQueueTimeoutMS=5000`,
  `socketTimeoutMS=15000`, `connectTimeoutMS=10000`, plus per-query `max_time_ms` on all routes.
- `/api/leads` is paginated with a lean projection; the row count is decoupled onto the analytics pool.
- Lean, consolidated index set (**16 indexes** on `leads`, deliberately reduced from 57 to avoid
  planner stalls and the 64-index cap).
- Frontend does not retry 503/504 and pauses polling when hidden — it is not the source of load.
- Transient Mongo errors are already mapped to graceful 503s (so the app degrades cleanly, but it
  cannot function while there is no reachable primary).

**Please confirm**
1. Current production tier name + connection limit.
2. That app and DB are in the **same region**.
3. Number of backend replicas (total connections = (80 + 20) × replicas must fit the tier).
4. Root cause of the primary loss at the timestamp above (so we can prevent recurrence).

Thank you — this is impacting live clinic operations, so a fast turnaround is appreciated.

— HomeIVF CRM team
