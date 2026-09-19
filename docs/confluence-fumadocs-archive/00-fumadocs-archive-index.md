# Fumadocs archive (public docs staging)

**Purpose:** Mirror of upcoming [public docs](https://docs.efficientai.cloud) (`docs-fumadocs/`) while that repo path is under parallel edit. Content here is **customer-facing** quality — copy into Fumadocs when the tree is free.

**Git source of truth:** `docs/confluence-fumadocs-archive/` on branch `otel-traces`.

**Technical TDDs (internal):** [Voice Call Traces & Observability (Index)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/69959682) — architecture deep dives, scaling TDD, latency explainer for support.

---

## Monitoring → Call Traces

| Page | Audience | File |
| --- | --- | --- |
| Call Traces — overview | Everyone | `monitoring/call-traces/01-overview.md` |
| Latency metrics (p50, p90, p95) | Support, sales, customers | `monitoring/call-traces/02-latency-metrics.md` |
| Architecture & scaling | Engineers, SRE | `monitoring/call-traces/03-architecture-and-scaling.md` |
| Pipecat & OTLP integration | Customer engineers | `monitoring/call-traces/04-pipecat-otlp-integration.md` |

**Baseline:** OTLP ingest with **S3 WAL → `worker-traces` → ClickHouse**; Postgres control plane only. Setup via `GET /api/v1/observability/traces/setup` (not a separate “Connect Pipecat” tab).

---

## When Fumadocs is unlocked

1. Copy each page into `docs-fumadocs/content/docs/monitoring/call-traces/*.mdx`.
2. Restore MDX frontmatter and `:::info` admonitions.
3. Fix internal links to `/docs/monitoring/call-traces/...`.
4. Archive or delete this Confluence folder after publish to docs.efficientai.cloud.
