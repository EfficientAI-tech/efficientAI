# Call-import sharding load validation (Phase 11)

Scenarios A–D from the internal Confluence runbook should be executed on AWS staging
(1 catalog + 5–6 row RDS instances) after enabling `database.sharding.enabled`.

**Operator quick reference:** [Call Import Scaling — Operator Handbook (Confluence)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/59932681).

## Exit criteria

- Row shard CPU ≤ 75% under scenario D (25k-row eval)
- Catalog CPU ≤ 50%
- No connection pool exhaustion (`pool_timeout` / PgBouncer queue depth stable)

## Scenarios (summary)

| ID | Description |
|----|-------------|
| A | Single import materialize + legacy import fetch |
| B | Unified eval pipeline, full metric set |
| C | Concurrent workspaces (fair dispatch) |
| D | 25k rows, max concurrency |

## Manual audio upload chunking

Large manual uploads should be sent in chunks of about 25 files per request (the UI does this automatically). The API rejects more than 100 files per request on `/audio-upload` and `/audio-append`.

Record results in the customer sign-off doc after GCP production sizing is confirmed.
