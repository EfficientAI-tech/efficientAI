> **Doc role:** Scaling deep-dive under [Voice Call Traces & Observability (Index)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/69959682).

# TDD: Call Traces — Scaling Architecture & Bottleneck Analysis

**Version:** 1.0  
**Date:** September 2026  
**Repo:** efficientAI  
**Audience:** Platform engineers, SRE, architects, sales/solutions (capacity section)  
**Companion docs:** [Main Call Traces TDD](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/68616193) · [Latency Metrics](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/71434241) · [Call Import Scaling](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/59899905)

**Purpose:** Document how call-trace ingest scales today, where bottlenecks move as we add capacity (HTTP → async → gRPC → collector), how proven telemetry stacks solve the same problems, and a decision matrix for SaaS-level scale (thousands of concurrent calls, millions of traces).

---

## 0. Summary

EfficientAI ingests **OpenTelemetry spans** from voice agents during live calls. Unlike batch analytics (call import, evaluations), trace ingest is **continuous, high-frequency, and latency-sensitive** — spans arrive every few seconds for the entire call duration.

**What we built (Phase 2 + Layout 3):**
- Thin API: stage raw OTLP → **202** in milliseconds
- Dedicated `worker-traces` Celery queue: parse, correlate, append-only batch INSERT
- Debounced derive: turns + p50/p90/p95 without O(all spans) per batch
- S3 offload on close: PG holds live spans only during the call
- Rate limits, idle sweep, staging retention

**Capacity shift:**

| Era | Comfortable concurrent OTLP calls | Primary bottleneck |
| --- | --- | --- |
| Phase 1 (sync JSONB rewrite) | 10–20 | API CPU + Postgres row locks |
| Phase 2 + Layout 3 (now) | 100–500 (with worker scale-out) | `worker-traces` throughput, then Postgres writes |
| Phase 3 (OTel Collector + gRPC) | 2,000–10,000+ ingest | Postgres catalog + derive CPU |
| Phase 4 (shard / columnar TSDB) | 10,000+ concurrent, 100M+ traces | Cross-tenant query cost, retention economics |

**Key insight for brainstorming:** Each optimization **moves** the bottleneck, it does not remove it. Faster ingest (gRPC, collector) pushes pressure to **Postgres write IOPS**, **derive CPU**, **S3 close spikes**, and **list/query paths**. Plan each layer independently.

---

## 1. What we are scaling (workload model)

### 1.1 Per-call traffic profile

Typical Pipecat voice agent with 5s OTLP export interval:

| Metric | Typical range |
| --- | --- |
| Call duration | 2–8 minutes (support calls longer) |
| Spans per call | 40–120 (STT, LLM, TTS, turn boundaries) |
| OTLP HTTP batches per call | 24–96 (~1 batch per 5s) |
| Spans per batch | 1–5 |
| Bytes per batch (JSON OTLP) | 2–50 KB |
| Derive runs per call | ~20–100 (debounced to ~1 per 3s while active) |

### 1.2 Aggregate at scale

| Concurrent calls | Ingest req/s | Span batch INSERTs/s | Derive jobs/s (debounced) | Open trace rows |
| --- | --- | --- | --- | --- |
| 20 | ~4 | ~4 | ~7 | 20 |
| 100 | ~20 | ~20 | ~33 | 100 |
| 500 | ~100 | ~100 | ~167 | 500 |
| 2,000 | ~400 | ~400 | ~667 | 2,000 |
| 10,000 | ~2,000 | ~2,000 | ~3,333 | 10,000 |

**Storage after close (per 1M calls):** ~150 GB span JSON in S3; ~1 GB trace headers + turns in Postgres.

### 1.3 What is different from generic APM

| Generic APM (Datadog, Honeycomb) | EfficientAI call traces |
| --- | --- |
| Fire-and-forget spans; query later | **Live UI** during call (turns, waterfall updating) |
| Trace = request lifecycle | Trace = **multi-minute session** with business ID (`call_short_id`) |
| Vendor stores everything | We **derive product metrics** (Listen/Think/Speak, p50) |
| Customer sends to vendor endpoint | We **correlate** across concurrent calls per workspace |
| Retention = vendor problem | We mix **Postgres (hot)** + **S3 (cold)** + Calls hub list |

This is closer to **session observability** than request tracing — design choices from request-tracing stacks do not map 1:1.

---

## 2. Current implementation (Phase 2 + Layout 3)

### 2.1 Architecture

```
Customer Pipecat / SDK
        │  OTLP HTTP POST (~5s)
        ▼
┌───────────────────────────────────────────────────────────────┐
│  API (FastAPI)                                                 │
│  • Auth (API key) + workspace scope                            │
│  • Rate limit (Redis, 120/min per key default)                 │
│  • INSERT synthetic_trace_ingest_staging (raw bytes)           │
│  • Enqueue process_staged_otlp(staging_id)                     │
│  • Return 202                                                │
└───────────────────────────┬───────────────────────────────────┘
                            │ Celery (Redis broker)
                            ▼
┌───────────────────────────────────────────────────────────────┐
│  worker-traces (queue: traces, concurrency 8 threads default)  │
│  process_staged_otlp  → parse, correlate, INSERT span_batch  │
│  derive_trace_turns   → turns JSON + p50/p90/p95 on header     │
│  close_and_offload    → S3 spans.json, DELETE batches        │
│  sweep_idle_traces    → close if idle ≥120s (beat every 30s) │
│  sweep_staging_ingest → delete staging >48h (beat hourly)    │
└───────────────────────────┬───────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   Postgres            Redis               S3
   (headers,           (broker,            (spans.json
    batches,            debounce,           on close)
    staging,             rate limits)
    turns)
```

### 2.2 Data stores and lifetimes

| Store | Table / object | Lifetime | Purpose |
| --- | --- | --- | --- |
| Postgres | `synthetic_call_traces` | Permanent | List row, status, latencies |
| Postgres | `synthetic_trace_payloads` | Permanent | Derived turns (waterfall) |
| Postgres | `synthetic_trace_span_batches` | **Open call only** | Append-only OTLP batches |
| Postgres | `synthetic_trace_ingest_staging` | ≤48h | Raw OTLP before worker parse |
| S3 | `.../traces/{trace_uuid}/spans.json` | Permanent (no TTL yet) | Cold span archive |
| Redis | Celery + locks + rate keys | Seconds–hours | Not span storage |

**S3 key:**
`{prefix}organizations/{org_id}/workspaces/{workspace_id}/traces/{trace_uuid}/spans.json`

One object per **trace session** (UUID). `call_short_id` is the business-facing 6-digit ID.

### 2.3 Current infra (docker-compose / staging)

| Service | Role | Scale note |
| --- | --- | --- |
| `api` | HTTP ingest + UI API | Horizontally scalable; stateless |
| `db` (Postgres 15) | Single catalog instance | **Not sharded for traces today** |
| `redis` | Celery broker | Single instance |
| `worker-traces` | Trace Celery tasks | Dedicated queue; scale replicas |
| `beat` | Periodic sweeps | **Single replica** (do not scale) |
| S3 | Span archive | Unlimited; per-close PUT latency |

**Existing sharding elsewhere:** `app/db_sharding/` routes evaluator payloads and call recordings to data shards. **Traces are catalog-only today** — they do not use live-entity sharding yet.

### 2.4 Configuration (defaults)

| Setting | Default | Effect |
| --- | --- | --- |
| `defer_parse_to_worker` | `true` | Layout 3 thin API |
| `rate_limit_per_minute` | `120` | Per API key ingest cap |
| `derive_debounce_seconds` | `3` | Coalesce derive jobs per trace |
| `idle_close_seconds` | `120` | Auto-close idle traces |
| `staging_retention_hours` | `48` | Staging cleanup |
| `max_body_bytes` | 4 MB | Per OTLP POST |

### 2.5 Validated numbers (local, Pipecat WebRTC)

| Step | Observed |
| --- | --- |
| API 202 ack | Fast path (staging INSERT only) |
| `process_staged_otlp` | ~30–50 ms |
| `close_and_offload_trace` | ~1.75 s (derive + S3 + batch delete) |

Load test harness: `scripts/load_test_trace_ingest.py` (default 20 concurrent calls, 5s interval).

---

## 3. Before vs after (capacity comparison)

| Dimension | Phase 1 | Phase 2 + Layout 3 (now) |
| --- | --- | --- |
| Ingest path | Sync in API: parse + append + derive + commit | Stage bytes → 202; worker parses |
| Span write pattern | UPDATE full JSONB array every batch | INSERT append-only batch row |
| Derive | Every batch, O(all spans) | Debounced worker job, ~3s |
| Span retention in PG | Entire call + forever | Open call only; S3 on close |
| API p95 under load | 100–200 ms+ | Target <50 ms ack |
| Comfortable concurrent calls | **10–20** | **100–500** (workers + PG) |
| Rate limiting | None | Redis per API key |
| List pagination | Offset | Keyset cursor + 90-day window |

**Rate limit reality check:** 120 req/min ≈ 12 req/min per call at 5s interval → **~10 concurrent calls per API key** before 429 unless limit is raised or keys are sharded per deployment.

---

## 4. Bottleneck map — current infra

As load increases, failures appear in a predictable order:

```
Load increases →
  ① API rate limit (429)
  ② worker-traces queue depth (staging backlog, stale UI metrics)
  ③ Postgres: span_batch INSERT IOPS + index growth
  ④ Postgres: derive reads all batches for trace (CPU + IO)
  ⑤ Redis broker memory / Celery fan-out
  ⑥ S3 PUT spike when many calls end simultaneously
  ⑦ List/query: synthetic_call_traces scan without retention
```

### 4.1 Component-by-component

| Component | Symptom at limit | Rough trigger | Mitigations |
| --- | --- | --- | --- |
| **API** | 429, connection exhaustion | Rate limit; single pod CPU | Raise limit; scale pods; gRPC binary (Phase 3) |
| **Redis** | Celery lag, rate limit false negatives | 10k+ tasks/min backlog | Dedicated Redis; split broker from cache |
| **worker-traces** | Staging rows pile up; metrics minutes stale | Queue depth > concurrency × 10 | More replicas; partition queue by org |
| **Postgres writes** | INSERT latency p95 >100ms | 100+ batch INSERTs/s sustained | Connection pool tuning; batch COPY; shard writes |
| **Postgres derive** | Worker CPU bound on SELECT batches | 500+ concurrent open traces | Pre-aggregate in Redis; incremental derive; columnar store |
| **Postgres list** | Slow Calls hub | 100k+ rows/workspace, no TTL | Retention policy; rollups; separate list index |
| **S3 close** | Close task retries | 1000+ simultaneous hangups | Async multipart; queue close separately |
| **beat** | Duplicate sweeps if scaled wrong | Multiple beat instances | Keep beat single replica |

### 4.2 Postgres — why it becomes the ceiling

Even with Layout 3, **every active call** generates:
- 1 staging INSERT per batch (deleted after process)
- 1 span_batch INSERT per batch
- Periodic header UPDATE on derive
- On close: read all batches → S3 → DELETE batches

At **2,000 concurrent calls** (~400 INSERTs/s to `synthetic_trace_span_batches`):
- Single Postgres 15 (default docker) saturates WAL and disk IOPS
- Index `(synthetic_call_trace_id, seq)` grows with open calls
- Connection count: API + N workers × pool size

**Traces are not on data shards today** — all write load hits **catalog Postgres**, same instance as org/workspace metadata and list queries.

### 4.3 What gRPC / OTel Collector changes (and what it does not)

| Layer | HTTP + Layout 3 today | + OTel Collector gRPC (Phase 3) |
| --- | --- | --- |
| Customer → edge | JSON HTTP POST to API | gRPC OTLP to Collector (or API) |
| API CPU | Low (staging only) | **Lower or bypassed** — collector receives |
| Payload size | JSON verbose | Protobuf ~40–60% smaller |
| Ingest throughput | ~100–500 concurrent | **2,000–10,000+** at collector tier |
| Parse location | worker-traces | Collector processors or still worker |
| **Postgres writes** | Same batch INSERT rate | **Unchanged** — still N INSERTs per call per interval |
| **Derive CPU** | Same | **Unchanged** |
| **Bottleneck** | Worker + PG | **Shifts to Postgres + derive** |

**Conclusion:** gRPC/collector solves **ingress and fan-in**, not **storage and live derive**. Without Phase 4 storage changes, adding collector only moves the firehose closer to Postgres.

---

## 5. How proven telemetry architectures work (and what we borrow)

### 5.1 Comparison matrix

| System | Ingest model | Hot storage | Cold storage | Query model | Fit for our live-call UI |
| --- | --- | --- | --- | --- | --- |
| **Prometheus** | Pull / remote write scrape | In-memory TSDB per metric | Blocks on disk; compaction | PromQL aggregates | ❌ Wrong model — metrics not spans; no per-call waterfall |
| **Grafana Mimir / Cortex** | Remote write | Distributed TSDB | Object storage backend | PromQL / LogQL | ⚠️ Good for **dashboards**, not span detail |
| **Grafana Tempo** | OTLP gRPC ingest | Ingester → block buffer | S3/GCS blocks | TraceQL (limited) | ✅ Span storage pattern; ❌ no built-in turn derive |
| **Loki** | Push logs | Index + chunks | S3 | LogQL | ❌ Logs not structured spans |
| **Jaeger** | OTLP / Thrift | Cassandra / ES / badger | S3 (v2) | Trace search | ✅ Reference OTLP pipeline; UI is trace-centric not product-centric |
| **OpenTelemetry Collector** | OTLP gRPC/HTTP | Processor pipeline | Exporters | N/A (routing) | ✅ **Must-have** at scale for fan-in, batch, retry |
| **Honeycomb** | Direct SDK / OTLP | Columnar in-house | Vendor | Fast arbitrary queries | ✅ Product feel; $$$; we replicate **derived fields** only |
| **Datadog APM** | Agent + intake | Vendor shard | Vendor | APM UI | ✅ Gold standard UX; not our storage |

### 5.2 Prometheus + Grafana — why not for call traces

**Prometheus model:**
- Scrapes **numeric time series** (counters, gauges, histograms)
- Pull-based or remote-write push
- Optimized for **aggregates**: `rate(http_requests[5m])`, alert rules
- Retention: days–weeks on local disk

**Why it does not replace our trace store:**
- Voice call observability needs **span attributes** (model name, transcript snippets, turn boundaries) — not just `latency_ms` gauge
- Waterfall UI needs **span parent/child** and ordered events per call
- p50/p90/p95 per call are **derived from span set**, not pre-scraped histograms

**What we CAN use Prometheus for (Phase 3+):**
- Platform **health** metrics: `trace_ingest_batches_total`, `worker_queue_depth`, `staging_age_seconds`
- Alerting: staging backlog > threshold, derive lag, close failures
- Grafana dashboards for **ops**, not customer Calls hub

### 5.3 OpenTelemetry Collector — the standard scale pattern

```
SDK (Pipecat) → OTLP gRPC → Collector
                              ├─ processors: batch, memory_limiter, attributes
                              ├─ exporter: Kafka / SQS (buffer)
                              └─ exporter: our ingest API or direct worker consumer
```

**Why everyone uses it at scale:**
- **Backpressure:** `memory_limiter` drops or delays before OOM
- **Batching:** Amortize network and downstream writes
- **Fan-in:** Thousands of agents → few collector replicas → one export stream
- **Vendor-neutral:** Same agent config; swap exporter

**Our Phase 3 path:** Collector → (Kafka optional) → ingest consumer → same correlate/batch/derive pipeline. API bypassed for span body.

### 5.4 Grafana Tempo / Jaeger — span block storage

**Tempo pattern:**
- Ingester buffers spans → flushes **blocks** to S3
- Query frontend merges blocks for trace ID lookup
- Cheap at rest; query latency seconds acceptable for debug

**Applicable to us:**
- **Closed traces:** Already doing S3 `spans.json` — similar to Tempo block
- **Open traces:** Tempo keeps in ingester memory — we keep in Postgres batches for **live derive**

**Gap:** Tempo does not compute **turn rows** or **Calls hub list** — we need a **derived state layer** (Postgres header + turns) regardless.

### 5.5 Honeycomb / Datadog — product lesson

They solve:
- High-cardinality fields (call_id, model, workspace) at query time
- Sub-second trace UI for recent data
- Retention tiers (hot 15d, cold 90d)

**We replicate the product surface, not the storage engine:**
- Hot: Postgres header + turns (small, indexed)
- Warm: PG batches during call
- Cold: S3 spans on close
- At SaaS scale: need **columnar** or **search index** for "all calls where p90 > 2s last week"

---

## 6. Scaling phases — options per bottleneck

### Phase 2 (implemented) — 100–500 concurrent

| Bottleneck | Options |
| --- | --- |
| API | Layout 3 staging ✅; scale API pods |
| Worker | `worker-traces` replicas; increase concurrency |
| Rate limit | Per-org limits; separate ingest API keys per deployment |
| Postgres | Tune `shared_buffers`, WAL; PgBouncer; read replica for list |

### Phase 3 — 2,000–10,000 concurrent ingest

| Component | Option A | Option B | Option C |
| --- | --- | --- | --- |
| **Ingress** | OTel Collector gRPC | Collector + Kafka buffer | Dedicated ingest subdomain + WAF |
| **API bypass** | Collector → worker consumer | Collector → S3 raw → batch loader | gRPC stream to worker |
| **Staging** | Keep PG staging | Redis stream buffer | Kafka topic per org |
| **Derive** | Incremental derive (delta spans only) | Stream processor (Flink/ksql) | Pre-compute in collector attributes processor |
| **Metrics ops** | Prometheus + Grafana | Datadog agent | CloudWatch |
| **List UI** | Daily rollup table | Materialized view per workspace | Elasticsearch/OpenSearch for filters |

### Phase 4 — 10,000+ concurrent, 100M+ traces

| Problem | Options | Tradeoff |
| --- | --- | --- |
| **Span writes** | Shard `span_batches` by `workspace_id` | Reuse `db_sharding` pattern from call import |
| **Span writes** | TimescaleDB hypertable (time-partitioned) | Good append; derive still hard |
| **Span writes** | ClickHouse / DuckDB columnar | Excellent analytics; ops complexity |
| **Hot derive** | Redis sorted set per open trace | Fast incremental; memory cost |
| **Cold storage** | S3 + Athena / Trino | Cheap query; seconds latency OK for export |
| **Catalog** | Trace header on catalog; payloads on shard | Matches existing live-entity model |
| **Retention** | TTL: delete S3 after N days; archive Glacier | Compliance vs cost |
| **Multi-tenant fairness** | Per-org queue (like fair dispatch) | Prevents noisy neighbor on worker-traces |

### 6.1 Sharding traces — reuse existing pattern

We already have:
- `app/db_sharding/live_entity_router.py` — workspace + entity → shard_id
- Catalog row with `shard_id` pointer
- Payload tables on data shards

**Proposed trace sharding (Phase 4):**

| Table | Location |
| --- | --- |
| `synthetic_call_traces` (header, list) | Catalog (or catalog + workspace partition) |
| `synthetic_trace_span_batches` | **Data shard** by `workspace_id` |
| `synthetic_trace_payloads` (turns) | Data shard |
| S3 path | Unchanged (org/workspace in key) |

**Derive job:** Worker opens shard session for trace's `workspace_id`, reads batches locally, writes turns, updates catalog header.

### 6.2 Alternative: event stream as source of truth

```
OTLP → Collector → Kafka (topic: otlp.spans)
                      ├→ Consumer: live derive → Postgres header (small)
                      ├→ Consumer: batch writer → ClickHouse (analytics)
                      └→ Consumer: on close → S3 compacted JSON
```

**Pros:** Decouples ingest from storage; replay for bugs; natural backpressure  
**Cons:** Kafka ops; eventual consistency for live UI; team expertise

---

## 7. Decision matrix (brainstorming)

Use this table in architecture reviews. Score options 1–5 per criterion.

| Criterion | PG batches (now) | + Collector gRPC | Shard PG | Kafka + CH | Tempo-style S3 blocks |
| --- | --- | --- | --- | --- | --- |
| Live UI latency | ✅ Good | ✅ Good | ✅ Good | ⚠️ Seconds lag | ⚠️ Open trace hard |
| Ingest ceiling | ⚠️ ~500 | ✅ 5k+ | ✅ 2k+ writes | ✅ 10k+ | ✅ 10k+ |
| Ops complexity | ✅ Low | ⚠️ Medium | ⚠️ Medium | ❌ High | ⚠️ Medium |
| Reuse existing code | ✅ Yes | ✅ Mostly | ✅ Sharding exists | ❌ New stack | ⚠️ Partial |
| Query "slow calls" | ⚠️ SQL scan | ⚠️ SQL scan | ⚠️ Per-shard | ✅ Columnar | ❌ Trace ID only |
| Cost at 1M calls/mo | ⚠️ PG + S3 | ⚠️ + collector | ⚠️ + shards | ⚠️ + Kafka + CH | ✅ S3 heavy |

---

## 8. SaaS scale targets (north star)

| Tier | Concurrent OTLP calls | Traces/month | Ingest req/s | Architecture |
| --- | --- | --- | --- | --- |
| **Pilot** | 20 | 10k | ~4 | Phase 2 ✅ |
| **Growth** | 100–500 | 100k | ~20–100 | Phase 2 + worker scale ✅ |
| **Mid-market** | 2,000 | 1M | ~400 | Phase 3 collector + PG tune |
| **Enterprise** | 10,000 | 10M | ~2,000 | Phase 4 shard or stream + columnar |
| **Hyperscale** | 50,000+ | 100M+ | ~10,000 | Multi-region collector, cell-based tenancy |

**Not in scope for pilot:** Sub-second global trace search, unlimited retention, per-span billing.

---

## 9. Operational checklist

| Check | Command / location |
| --- | --- |
| Worker registered tasks | `celery -A app.workers.celery_app inspect registered` — must include `sweep_idle_traces` |
| Queue depth | Redis `LLEN traces` or Flower |
| Staging backlog | `SELECT count(*) FROM synthetic_trace_ingest_staging WHERE status='pending'` |
| Open traces | `SELECT count(*) FROM synthetic_call_traces WHERE status='open'` |
| Load test | `scripts/load_test_trace_ingest.py --concurrent-calls 100` |
| Docker stale worker | Rebuild `worker-traces` image when trace tasks missing |

---

## 10. Open questions for team brainstorm

1. **Live derive:** Stay Postgres-read-all-batches or move to Redis incremental state per open trace?
2. **Ingress:** Customer-facing Collector (self-hosted docs) vs managed collector endpoint?
3. **Sharding:** Trace batches on existing data shards vs dedicated trace cluster?
4. **Retention:** Default 90-day list window — enforce S3 lifecycle delete?
5. **Analytics:** Do we need ClickHouse for "all calls p90 > X" or is Postgres + rollup enough to 1M traces/mo?
6. **Fair dispatch:** Per-org `worker-traces` queue partition (like call import) for noisy neighbor?
7. **gRPC:** On API pod or only on Collector — security boundary for multi-tenant auth?
8. **Webhook calls:** Vapi/Retell traces never hit OTLP — unify metrics pipeline or keep separate?

---

## 11. Related code & config

| Area | Path |
| --- | --- |
| Ingest pipeline | `app/services/synthetic_traces/ingest_pipeline.py` |
| Span storage / S3 | `app/services/synthetic_traces/span_storage.py` |
| Worker tasks | `app/workers/tasks/trace_tasks.py` |
| Beat + routes | `app/workers/config.py` |
| Rate limits | `app/core/rate_limit.py` |
| Migrations | `084_trace_span_batches.py`, `085_trace_ingest_staging.py` |
| Sharding (existing) | `app/db_sharding/` |
| Load test | `scripts/load_test_trace_ingest.py` |
| Config | `traces:` in `config.yml` |

---

## 12. Document history

| Version | Date | Change |
| --- | --- | --- |
| 1.0 | Sep 2026 | Initial scaling TDD: bottlenecks, telemetry comparison, Phase 3–4 options |
