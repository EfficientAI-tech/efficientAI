# Call Traces — architecture & scaling

Technical overview of how EfficientAI ingests OTLP spans from voice agents, stores traces in **ClickHouse**, and routes the **Calls** hub UI.

Related: Call Traces overview · Latency metrics · Pipecat & OTLP integration

---

## Plain-English summary

Customers run **voice agents** (Pipecat, LiveKit, custom stacks) and need **per-turn STT → LLM → TTS latency**, model names, and conversation text — without building Honeycomb or Datadog themselves.

EfficientAI:

1. Mints a **6-digit Call ID** (`call_short_id`) per session.
2. Accepts **OpenTelemetry spans** over HTTP from the customer's bot (or in-process from Test Agent playground).
3. On the **recommended production path**, buffers raw OTLP on **S3**, processes on **`worker-traces`**, and persists spans and derived turns in **ClickHouse**.
4. Groups spans into **turn rows**, computes **p50 / p90 / p95**, and shows a **waterfall** in the Calls hub.

**Postgres** remains the **control plane** (organizations, workspaces, evaluator results, `evaluator_results.synthetic_call_trace_id` as an opaque UUID link to the trace). After migration **092**, legacy PG trace payload tables are removed — **ClickHouse is required** for trace list/detail at scale.

---

## Problem we solve

| Stakeholder | Need |
| --- | --- |
| **Customer engineering** | Drop-in OTLP export (Pipecat SDK or generic HTTP exporter) |
| **Sales / solutions** | Honest capacity answers and how p50 is calculated |
| **Platform / SRE** | Clear ingest boundaries: API edge vs async worker vs analytics store |
| **PM / frontend** | One Calls hub for OTLP traces and webhook calls — without mixing playground test data |

| Problem | Symptom |
| --- | --- |
| No stable call correlation | OTLP batches from concurrent calls land on wrong trace |
| OTel `trace_id` alone insufficient | Tracer restarts change trace ID; UI needs stable `#482931` |
| Mixed call sources | Same 6-digit ID in playground vs webhook opens wrong drawer |
| Playground pollution | Voice AI playground calls in production observability list |

---

## Solution overview

| Mechanism | Purpose |
| --- | --- |
| **`call_short_id` minting** | Server assigns 6-digit ID; stamped on every span + OTLP header |
| **Workspace + org scoping** | API key → org; `X-Workspace-Id` → workspace |
| **ClickHouse trace store** | Headers, observations, span queries for list/detail/waterfall |
| **S3 WAL batches** | Raw OTLP bytes under `traces/organizations/.../batches/{seq}.json` before worker parse |
| **Celery queue `traces`** | `process_s3_otlp_batch` jobs consumed only by **`worker-traces`** |
| **Deferred ingest (default at scale)** | API returns **202** after S3 PUT + enqueue; worker completes CH writes |
| **Turn mapper + percentiles** | Derives STT / LLM / TTS ms; computes p50 / p90 / p95 |
| **`source` on `call_recordings`** | `playground` vs `webhook` — API filters + drawer routing |
| **Idle auto-close (120s)** | Open traces close if spans stop arriving |
| **Redis live turns (optional)** | In-flight turn preview for open calls while spans stream |

**Key principle:** Correlate on **`call_short_id`**, not OTel `trace_id` alone.

---

## Architecture diagram

```
┌──────────────────────── Customer ────────────────────────┐
│  Voice agent (OTLP HTTP)     Vapi / Retell webhooks       │
└──────────────┬──────────────────────────┬──────────────────┘
               ▼                          ▼
┌──────────────────── EfficientAI ──────────────────────────┐
│  FastAPI observability routes    Playground in-process OTLP │
└──────────────┬──────────────────┬─────────────────────────┘
               ▼                  ▼
     Postgres (control plane)   S3 (WAL batches, audio, imports)
               │                  │
               │                  └──► worker-traces ──► ClickHouse
               └── evaluator_results.synthetic_call_trace_id ──► trace UUID
```

### Data flow

| From | Transport | Lands in |
| --- | --- | --- |
| Customer voice agent | `POST /api/v1/observability/traces` | S3 WAL → **worker-traces** → **ClickHouse** |
| Playground Test Agent | In-process OTLP exporter | Same ingest path as customer bots |
| Provider webhooks | `POST /observability/calls/webhook/...` | `call_recordings` (`source=webhook`) |
| Playground Voice AI | Playground APIs + provider poll | `call_recordings` (`source=playground`) |

---

## OTLP ingest flow (deferred path)

This is the **default** configuration for production scale (`defer_parse_to_worker` + `async_ingest_enabled` + `clickhouse.url`).

| Step | Component | Action |
| --- | --- | --- |
| 1 | **API** | Auth, rate limit, validate body size |
| 2 | **API → S3** | PUT raw OTLP (protobuf or JSON) to WAL batch path |
| 3 | **API → Redis** | Enqueue `process_s3_otlp_batch` on queue **`traces`** |
| 4 | **API → bot** | Respond **202 Accepted** (ingest not complete yet) |
| 5 | **`worker-traces`** | GET batch from S3, parse OTLP, INSERT ClickHouse, derive turns, delete WAL |
| 6 | **API / UI** | Read list, detail, spans from **ClickHouse** |

Bots only speak **HTTP to the API**. They never call the worker directly.

**Sync path (development / small pilots):** Set `defer_parse_to_worker: false` so the API parses OTLP and writes ClickHouse inline (higher API CPU and latency per batch).

**Session lifecycle**

| Step | Action |
| --- | --- |
| 1 | `ensure_trace_session()` (SDK) or `POST .../traces/sessions` mints `call_short_id` |
| 2 | Tracing hooks stamp spans + `X-EfficientAI-Call-Short-Id` on export |
| 3 | Exporter `POST /observability/traces` on an interval (~5s typical) |
| 4 | Worker dedupes spans, rebuilds turns, updates p50 / p90 / p95 on trace header |
| 5 | `close_trace_session()` on disconnect |

---

## Storage layout (logical)

| Store | Holds |
| --- | --- |
| **ClickHouse** | Trace headers, span observations, queryable list/filter, waterfall source |
| **S3** | Ingest WAL batches; optional compacted span archives on session close |
| **Postgres** | Evaluator runs, `synthetic_call_trace_id` link, `call_recordings` metadata |
| **Redis** | Celery broker; optional live-turn cache for open traces |

| `call_recordings` column | Values | Used for |
| --- | --- | --- |
| `call_short_id` | 6-digit | Correlation across surfaces |
| `source` | `playground` \| `webhook` | API scoping + drawer routing |
| `call_data` | Provider JSON | Transcript, cost, latency (webhook path) |

---

## Calls hub routing

**Route:** `/observability/calls`

| Tab | List API | Rows |
| --- | --- | --- |
| **Traces** | `GET /api/v1/observability/traces` | OTLP voice-agent traces |
| **Calls** | `GET /api/v1/observability/calls` | Webhook only (`source=webhook`) |

| User action | Query param | Panel |
| --- | --- | --- |
| OTLP trace row | `?trace={uuid}` | Pipeline trace drawer |
| Webhook call row | `?obs={call_short_id}` | Webhook call drawer |
| Evaluator link | `?result={evaluator_result_id}` | Evaluator drawer |

| Surface | In Calls hub? |
| --- | --- |
| OTLP traces | Yes (Traces tab) |
| Webhook production calls | Yes (Calls tab) |
| Playground Test Agent | No (linked from playground / evaluator) |
| Playground Voice AI | No |

**Same Call ID, different source:** The same 6-digit `call_short_id` can exist in `call_recordings` with `source=playground` vs `source=webhook`. Drawer routing uses `call_recording_source`, not `provider_platform` alone.

---

## Metrics computation

| Stage | Output |
| --- | --- |
| Parse spans | Normalized span dicts |
| Group by turn | `stt_ttfb_ms`, `llm_ttfb_ms`, `tts_ttfb_ms`, `sut_response_latency_ms` |
| Call percentiles | `response_latency_p50_ms`, `p90`, `p95` |
| Component percentiles | Per-stage p50 on trace header |

| Turn field | OTLP source |
| --- | --- |
| `stt_ttfb_ms` | `metrics.ttfb` on `stt` span (seconds × 1000) |
| `llm_ttfb_ms` | `metrics.ttfb` on `llm` span |
| `tts_ttfb_ms` | `metrics.ttfb` on `tts` span |
| `sut_response_latency_ms` | `turn.user_bot_latency_seconds` on `turn` span |

Full formulas: Latency metrics.

---

## Scaling

### Baseline (ClickHouse + deferred ingest)

| Metric | Design point |
| --- | --- |
| Concurrent OTLP calls per workspace | **~100–500+** (staging / pilot targets; validate with your CH cluster) |
| Spans per call | ~40–120 typical Pipecat pipelines |
| OTLP batches per call | ~24–96 (~5s export interval) |
| API response on ingest | **202** on deferred path (milliseconds to S3 + enqueue) |
| Idle auto-close | **120 seconds** |

### Throughput model

| Scenario | Concurrent OTLP | Notes |
| --- | --- | --- |
| Team dev | 5–20 | Single API + worker-traces sufficient |
| Pilot customer | 50–100 | Monitor CH insert rate and S3 WAL depth |
| Single tenant | 100–500 | Scale `worker-traces` replicas; CH vertical/horizontal scale |
| Multi-tenant | 500+ | Rate limits per org, CH capacity planning, optional OTel Collector at edge (roadmap) |

### Operational requirements

| Requirement | Why |
| --- | --- |
| `clickhouse.url` configured | Span storage and trace APIs |
| `worker-traces` running (queue **`traces`**) | Without it, deferred ingest stalls after S3 WAL |
| `defer_parse_to_worker: true` (prod) | Keeps API pods CPU-bound on auth + WAL only |
| Migration **092** applied | PG span tables removed; missing CH fails fast with clear error |

### Roadmap (not required for current pilots)

| Phase | Changes | Unlocks |
| --- | --- | --- |
| **Edge collector** | OTel Collector gRPC in customer VPC | Lower API fan-in, mTLS |
| **Rollups / retention** | CH TTL + pre-aggregated dashboards | Longer history at lower cost |

---

## Authentication & headers

| Header | Purpose |
| --- | --- |
| `X-API-Key` | Organization auth |
| `X-Workspace-Id` | Tenant isolation |
| `X-EfficientAI-Call-Short-Id` | Route OTLP batch (or span attribute) |

Key span attributes: `efficientai.call_short_id`, `gen_ai.operation.name` (`stt` / `llm` / `tts`), `metrics.ttfb` (seconds), `turn.number`.

---

## API limits

| Setting | Value |
| --- | --- |
| Trace list default / max `limit` | 50 / 200 |
| Calls hub UI page size | 25 |
| Open trace idle auto-close | **120 seconds** |
| `call_short_id` range | 100000–999999 |

| Environment | API base |
| --- | --- |
| Local | `http://localhost:8000` |
| Sandbox (hosted pilots) | `https://sandbox.efficientai.cloud` |

---

## Provider vs OTLP metrics

For Vapi / Retell / ElevenLabs playground calls we **display provider fields** from `call_data`. We do not recompute p50 in our backend for those.

| Source | p50 in UI | Computed by us? |
| --- | --- | --- |
| OTLP / Pipecat | `response_latency_p50_ms` | **Yes** |
| Vapi | `turnLatency`, averages | **No** |
| Retell | `latency.e2e.p50` | **No** |

See Latency metrics — OTLP vs provider metrics.
