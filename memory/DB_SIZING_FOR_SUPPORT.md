# HomeIVF CRM — Production Database Sizing Request (for Emergent Support)

## Context
- App: HomeIVF CRM (FastAPI + MongoDB + React), live on production.
- Data: **120,000+ leads** and growing (~650 new Meta leads/day + call/activity/status writes).
- Concurrency: **24 callers working continuously** + admins/managers running dashboards & reports.
- Symptom we hit: frequent HTTP 500s and one **total outage** (Cloudflare 520 – origin returned empty responses) under load. Root cause was **connection-pool / database saturation** — interactive caller queries had to wait for DB connections held by heavy analytical queries, cascading into worker collapse.

## What we already did in the application code
- Split into **two connection pools** (interactive 80 / analytics 20) so heavy reporting/backfill can never starve caller/login connections.
- Added fast-fail (`waitQueueTimeoutMS`) + per-query time limits so a slow query aborts instead of hanging.
- Optimized dashboards (progressive load), de-duplicated Meta webhook writes, and hardened the error logger so it cannot amplify an incident.

## What we need from the database tier
Please confirm the current production MongoDB tier and, if it is a **shared/low tier (e.g. M0/M2/M5)**, upgrade it. Shared tiers cap connections (~500) and throttle CPU/IOPS — that is the classic cause of the pool-exhaustion 500s under our concurrent load.

### Recommended spec (dedicated cluster)
| Metric | Recommended | Minimum |
|---|---|---|
| Tier | **Atlas M20 (or equivalent dedicated)** | M10 |
| RAM | **4 GB** (keeps the ~120k dataset + ~45 indexes resident in memory → avoids slow disk reads under load) | 2 GB |
| vCPU | 2 | 2 |
| Max connections | 3,000 (M20) | 1,500 (M10) |
| Storage | 10 GB+ with provisioned IOPS | — |
| Region | **Same region as the app deployment** (minimise per-query network latency) | — |

### Why M20 over M10
- 24 concurrent callers + admins + ~650 writes/day is a **write- and connection-heavy** workload.
- 4 GB RAM keeps the full working set (leads + indexes ≈ 0.7–1 GB today) in memory with headroom to grow to 200k+ leads.
- Avoids the CPU/IOPS throttling that shared tiers impose.

### Also please confirm
1. Current tier name + connection limit of the production database.
2. That the app and DB are in the **same region**.
3. Whether the deployment runs **multiple backend replicas** — if so, total connections = (80 + 20) × replicas; the tier must allow that comfortably.

Thank you.
