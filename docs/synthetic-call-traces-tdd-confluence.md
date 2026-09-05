> **Doc role:** Canonical TDD in [Voice Call Traces & Observability (Index)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/69959682).

# TDD: Call Traces — Pipecat OTLP Observability (Architecture & Scaling)

**Version:** 1.0 (staging)  
**Date:** March 2026  
**Repo:** efficientAI  
**Audience:** Platform engineers, SREs, sales/solutions architects, enterprise customers  
**UI:** `/observability/calls` (traces tab)  
**API prefix:** `/api/v1/observability/traces`

**Style reference:** [System Design — Call Import Concurrency](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/48103425) · [Usage & Cost Tracking — Architecture Guide](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/63045633)

---

## 0. Plain-English summary (read this first)

Customers run **Pipecat voice agents** (or connect Vapi/Retell webhooks). During each call they need to see **per-turn STT → LLM → TTS latency**, model names, and conversation text — without building Honeycomb/Datadog themselves.

EfficientAI solves this by:

1. Minting a **6-digit Call ID** (`call_short_id`) per session.
2. Ingesting **OpenTelemetry spans** from the customer's bot (or in-process from our Test Agent playground).
3. Grouping spans into **turn rows**, computing **p50/p90/p95**, and showing a **waterfall** in the Calls hub.

**What we do not do in v1:** Dollar cost from OTLP spans (cost comes from provider `call_data`). Async ingest at enterprise scale (planned Phase 2). Shard trace rows across data shards (catalog Postgres only).

Think of it like call import fair dispatch: **backlog and correctness live in Postgres**; the hot path today is **sync HTTP ingest** (simple for customers, caps throughput until Phase 2).

---

## 1. Problem statement

### 1.1 What teams need

| Stakeholder | Need |
| --- | --- |
| **Customer engineering** | Drop-in OTLP export from Pipecat; see latency waterfall without running their own observability stack |
| **Sales / solutions** | Honest answers on concurrent call capacity, how p50 is calculated, and what breaks at scale |
| **Platform / SRE** | Clear boundaries: which service owns ingest, where rows live, playground vs production isolation |
| **PM / frontend** | One Calls hub for OTLP traces and webhook production calls — without mixing playground test data |

### 1.2 What went wrong without this design

| Problem | Symptom |
| --- | --- |
| **No stable call correlation** | OTLP batches from 20 concurrent WebRTC calls hit one URL — spans could land on the wrong trace row |
| **OTel `trace_id` alone is insufficient** | Tracer restarts mid-call change OTel trace ID; UI needs a stable business ID (`#482931`) |
| **Mixed call sources** | Same 6-digit ID can exist in `call_recordings` (playground) and (webhook) — UI opened wrong drawer |
| **Playground pollution** | Voice AI playground calls appeared in production observability list |
| **Metrics confusion** | Sales asked "do you compute p50?" — answer differs for OTLP (yes) vs Vapi/Retell (provider fields) |
| **Scaling opacity** | Sync ingest + full JSONB span rewrite per batch — fine for 10–20 calls, breaks at 500+ without Phase 2 |

### 1.3 Requirements (v1)

* **Per-call isolation** via `call_short_id` + `workspace_id` + API key
* **OTLP HTTP ingest** for customer Pipecat bots; **in-process** export for Test Agent playground
* **Computed latency** from span `metrics.ttfb` and Pipecat turn attributes
* **Production Calls hub** lists webhook calls (`source=webhook`) and OTLP traces — **not** playground recordings
* **Pilot scale:** 10–20 concurrent OTLP calls per workspace on staging
* **Honest enterprise path:** documented Phase 2 (async queue, S3 spans, rate limits)

---

## 2. Solution overview

Eight mechanisms work together:

| # | Mechanism | Purpose |
| --- | --- | --- |
| 1 | **`call_short_id` minting** | Server assigns 6-digit ID at session start; stamped on every span + OTLP header |
| 2 | **Workspace + org scoping** | API key → org; header → workspace; ingest never crosses tenants |
| 3 | **Three-table trace storage** | Header (list), turns JSON (waterfall), raw spans (debug) — avoid parsing OTLP on every page load |
| 4 | **Sync OTLP ingest** | HTTP request parses, appends spans, rebuilds turns, commits — simple customer SDK |
| 5 | **Turn mapper + percentiles** | `otlp_mapper.py` derives STT/LLM/TTS ms; `compute_trace_latency_summary()` for p50/p90/p95 |
| 6 | **`source` column on `call_recordings`** | `playground` vs `webhook` — API filters + drawer routing |
| 7 | **Idle auto-close (120s)** | Open traces close without SDK `close` if spans stop arriving |
| 8 | **Poll-based live SSE** | Webhook calls stream `live_transcript` from Postgres (no Redis pub/sub v1) |

**Key design principle:** We correlate on **`call_short_id`**, not OTel `trace_id` alone. Playground and production observability are **separate surfaces** even when the Call ID format looks the same.

---

## 3. System design — key decisions and why

| Decision | What we chose | Why |
| --- | --- | --- |
| **Call correlation ID** | 6-digit `call_short_id` (100000–999999) | Human-readable in UI; uniqueness check on mint |
| **OTLP transport (customer)** | Sync HTTP POST to API | Lowest integration friction; no collector required for pilots |
| **OTLP transport (Test Agent)** | In-process `InternalOtlpSpanExporter` | No HTTP hop; same turn mapper as customer OTLP |
| **Span storage** | Full JSON array in Postgres JSONB | Simple v1; rewrite entire array each batch (scaling tradeoff) |
| **Trace sharding** | Catalog Postgres only | Unlike call imports — no hash routing to data shards |
| **Percentile method** | Nearest-rank on sorted per-turn SUT values | Deterministic, matches `trace_service.py` — not linear interpolation |
| **Production calls list** | `source == webhook` filter | Playground Voice AI never in observability hub |
| **Live transcript** | 1s Postgres poll SSE | Works for staging volume; DB load grows with concurrent live calls |
| **Rate limiting** | Not enforced on trace routes (v1) | Config may define limits; wired in Phase 2 |
| **Cost from OTLP** | Not computed | Dollar cost from provider `call_data` (§11.5) |

---

## 4. High-level architecture

```
┌─────────────────────────────── Customer ───────────────────────────────┐
│  Pipecat bot (OTLP HTTP)          Vapi / Retell / ElevenLabs webhooks   │
└───────────────┬───────────────────────────────┬────────────────────────┘
                │                               │
                ▼                               ▼
┌────────────────────────── EfficientAI ─────────────────────────────────┐
│  FastAPI (observability routes)    Voice Playground (in-process OTLP)     │
│  Celery workers (eval, finalize)   SSE live-events (poll-based)          │
└───────┬──────────────────┬──────────────────┬────────────────────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
┌────────────── Postgres catalog ──────────┐   ┌──── S3 / blob storage ────┐
│ synthetic_call_traces + payloads           │   │ evaluator audio, imports  │
│ call_recordings (playground | webhook)   │   └───────────────────────────┘
│ evaluator_results                        │
└──────────────────────────────────────────┘
```

### 4.1 Data flow summary

| From | Transport | Lands in |
| --- | --- | --- |
| Customer Pipecat bot | `POST /observability/traces` (OTLP) | `synthetic_call_traces` |
| Playground Test Agent | In-process `InternalOtlpSpanExporter` | `synthetic_call_traces` |
| Provider webhooks | `POST /observability/calls/webhook/...` | `call_recordings` (`source=webhook`) |
| Playground Voice AI | Playground APIs + provider poll | `call_recordings` (`source=playground`) |
| Evaluate / telephony | Celery tasks | `evaluator_results` + S3 audio |

### 4.2 Services & responsibilities

| Component | Role | Async? |
| --- | --- | --- |
| **FastAPI** | OTLP ingest, sessions, observability CRUD, webhooks, SSE | Sync HTTP for OTLP |
| **Voice Playground** | Test-agent in-process span export | In-process during call |
| **Celery `worker`** | Telephony finalize, evaluator runs | Yes |
| **Postgres (catalog)** | All trace + call metadata | Durable SoT — **not sharded** |
| **Redis** | Celery broker (imports/evals) | **Not** used for OTLP ingest v1 |
| **S3** | Evaluator audio, recordings | Durable |

---

## 5. Scaling — today vs future

### 5.1 Observed baseline (staging pilots)

| Metric | v1 design point |
| --- | --- |
| Concurrent OTLP calls per workspace | **10–20** |
| Concurrent webhook live calls (SSE) | **5–10** |
| Typical call duration | 2–8 minutes |
| Spans per call | ~40–120 |
| OTLP batches per call | ~24–96 (~5s exporter interval) |
| Ingest p95 @ low concurrency | < 200 ms per batch |
| Traces retained | Indefinite (no TTL v1) |

### 5.2 Throughput model

| Scenario | Concurrent OTLP calls | Ingest req/s | v1 (1 API pod) | Bottleneck |
| --- | --- | --- | --- | --- |
| Team dev | 5 | ~1 | ✅ Comfortable | — |
| Pilot customer | 20 | ~4 | ✅ Comfortable | — |
| Single tenant | 100 | ~20 | ⚠️ Monitor CPU + DB | Sync ingest + JSONB rewrite |
| Multi-tenant | 500 | ~100 | ❌ Phase 2 | API saturation, row locks |
| Enterprise | 2000+ | 400+ | ❌ Phase 3 | OTel collector + async queue |

### 5.3 Storage growth

| Volume | Est. span JSONB | Action |
| --- | --- | --- |
| 1,000 calls | ~150 MB | Fine |
| 10,000 calls | ~1.5 GB | Vacuum planning |
| 100,000 calls | ~15 GB | Retention policy |
| 1M calls | ~150 GB | S3 offload mandatory |

### 5.4 Phase roadmap

| Phase | Changes | Unlocks |
| --- | --- | --- |
| **Phase 1 (now)** | Sync ingest, catalog JSONB, 6-digit IDs | Pilots, 10–20 concurrent |
| **Phase 2** | Celery `traces` queue, S3 span blobs, rate limits | 100–500 concurrent |
| **Phase 3** | OTel Collector gRPC, daily rollups, retention | Enterprise dashboards, 2k+ |
| **Phase 4** | Trace shard table or Timescale | 1M+ traces |

### 5.5 Ingest write pattern (why sync ingest caps scale)

Every OTLP batch for one call:

1. `SELECT` full `spans` JSON array
2. Append + dedupe `(trace_id, span_id)`
3. `derive_turns_from_spans()` — re-derive from **all** spans
4. Recompute p50/p90/p95
5. `UPDATE` — single transaction

**Cost:** O(spans × batches), not O(new spans alone).

### 5.6 Configuration: v1 vs Phase 2 target

| Setting | Today (v1) | Phase 2 recommended |
| --- | --- | --- |
| Ingest path | Sync in API request | Celery `traces` queue |
| Span storage | Postgres JSONB array | S3 per trace; PG pointer |
| Rate limit | None on `/observability/traces` | 60–120 req/min per API key |
| List pagination | UI 25, API max 200 | Cursor + 90-day window |
| Idle auto-close | 120s | Configurable per workspace |
| Live SSE | 1s Postgres poll | Redis pub/sub or LISTEN/NOTIFY |

### 5.7 Before vs after (capacity)

| Scenario | Without observability | v1 (now) | Phase 2 (target) |
| --- | --- | --- | --- |
| Pilot: 20 concurrent OTLP calls | Customer runs own Datadog | ✅ Sync ingest OK | ✅ Async, <50ms ack |
| Single tenant: 100 concurrent | N/A | ⚠️ Degraded | ✅ 500–1000 with workers |
| 10k traces / workspace storage | N/A | ✅ ~1.5 GB catalog | ✅ S3 offload |
| Sales: "how is p50 computed?" | Vendor black box | ✅ Documented formula | Same |
| Playground in prod Calls hub | Mixed test + prod data | ✅ Filtered `source=webhook` | Same |

---

## 6. API limits & environments

| Setting | Value | Location |
| --- | --- | --- |
| Trace list default / max `limit` | 50 / 200 | `synthetic_traces.py` |
| Calls hub UI page size | 25 | `TestInsights.tsx` |
| Observability calls list `limit` | 100 | `observability.py` |
| Open trace idle auto-close | **120 seconds** | `OPEN_TRACE_IDLE_CLOSE_SECONDS` |
| `call_short_id` range | 100000–999999 | `generate_unique_call_short_id()` |

| Environment | API base |
| --- | --- |
| Local | `http://localhost:8000` |
| Staging | `https://staging.efficientai.cloud` |
| Production | Not GA for traces yet — same SDK, change `EFFICIENTAI_API_BASE` |

---

## 7. Database schema

### 7.1 Trace tables (catalog Postgres)

| Table | Purpose | Size per call |
| --- | --- | --- |
| `synthetic_call_traces` | Header: status, p50/p90/p95, turn_count | ~1 KB |
| `synthetic_trace_payloads` | Derived turns JSON (waterfall) | ~2–8 KB |
| `synthetic_trace_otel_payloads` | Raw spans JSON array | ~50–300 KB |

### 7.2 `call_recordings` (shared)

| Column | Values | Used for |
| --- | --- | --- |
| `call_short_id` | 6-digit | All surfaces |
| `source` | `playground` \| `webhook` | API scoping + drawer routing |
| `provider_platform` | vapi, retell, … | Provider panels |
| `call_data` | Provider JSON | Transcript, cost, latency |

### 7.3 Why three trace tables?

| Table | Query | Reason |
| --- | --- | --- |
| Header | `ORDER BY started_at DESC LIMIT 50` | Fast list without spans |
| Turns | Detail waterfall | No OTLP parse on page load |
| Raw spans | Debug tab | Full fidelity for support |

---

## 8. Unified Calls hub

**Route:** `/observability/calls` (`TestInsights.tsx`) — legacy `/calls`, `/call-traces` redirect here.

### 8.1 List tabs and APIs

| Tab | List API | Table | Rows |
| --- | --- | --- | --- |
| **Traces** | `GET /observability/traces` | `synthetic_call_traces` | OTLP / Pipecat |
| **Calls** | `GET /observability/calls` | `call_recordings` | Webhook only (`source=webhook`) |

### 8.2 Detail drawer routing

Frontend helper: `frontend/src/lib/callDetailRouting.ts` → `resolveTraceDrawerTargets()`.

**Drawer priority inside `TraceDetailDrawer`:** `callShortId` → `observabilityCallShortId` → `evaluatorResultId` → `traceId`.

| User action | Query / entry | Panel | Detail API |
| --- | --- | --- | --- |
| OTLP trace row | `?trace={uuid}` | `SyntheticCallTracePanel` | `GET /observability/traces/{id}` |
| Webhook call row | `?obs={call_short_id}` | `ObservabilityCallDetailPanel` | `GET /observability/calls/{id}` |
| Evaluator deep link | `?result={evaluator_result_id}` | `EvaluatorCallDetailPanel` | `GET /evaluator-results/{id}` |
| Playground Voice AI | `/playground` Voice AI tab | `ProviderCallTracePanel` | `GET /playground/call-recordings/{id}` |
| Playground Test Agent | `/playground` Test Agents tab | Full page + optional drawer | `GET /evaluator-results/{id}` + OTLP trace |

**Routing rule:** The same 6-digit `call_short_id` can exist in `call_recordings` with different `source` values (`playground` vs `webhook`). Drawer routing must use `call_recording_source` (resolved from linked `call_recordings.source`), not `provider_platform` alone. Voice AI platforms in the routing set: `vapi`, `retell`, `elevenlabs`, `smallest`.

### 8.3 Surface map

| Surface | In Calls hub? | Table / source |
| --- | --- | --- |
| OTLP traces | Yes (traces tab) | `synthetic_call_traces` |
| Webhook production calls | Yes (calls tab) | `call_recordings`, `source=webhook` |
| Playground Test Agent | No | `evaluator_results` + trace |
| Playground Voice AI | No | `call_recordings`, `source=playground` |

---

## 9. End-to-end flows

### 9.1 OTLP ingest (customer Pipecat)

| Step | Who | Action |
| --- | --- | --- |
| 1 | Customer bot | `ensure_trace_session()` → mint `call_short_id` |
| 2 | SDK | `setup_pipecat_worker_tracing()` → stamp spans + headers |
| 3 | Pipecat | `PipelineWorker(enable_tracing=True)` → `stt`/`llm`/`tts` spans |
| 4 | OTel exporter | `POST /observability/traces` (~every 5s) |
| 5 | Ingest | Dedupe, rebuild turns, update p50/p90/p95 |
| 6 | Bot disconnect | `close_trace_session()` or 120s idle auto-close |
| 7 | User | `/observability/calls` → waterfall |

### 9.2 Test Agent (in-process — no HTTP OTLP)

| Piece | Module |
| --- | --- |
| Span stamping | `playground_tracing.py` |
| Export | `internal_otlp_exporter.py` → `ingest_otlp_spans()` |
| UI | `EvaluatorCallDetailPanel` → Pipeline tab |

Same turn rows as customer OTLP — only transport differs.

### 9.3 Webhook observability calls

| Step | Action |
| --- | --- |
| Ingest | `POST /observability/calls/webhook/{api_key}` → `call_recordings`, `source=webhook` |
| Live transcript | `GET /observability/calls/{id}/live-events` — 1s poll SSE |
| Evaluate | `POST /observability/calls/{id}/evaluate` → `evaluator_result` |

Webhook upsert scoped to `workspace_id`. Playground rows skipped (`skipped_playground`).

---

## 10. Correlation & multi-tenancy

### 10.1 Three-key routing (every OTLP batch)

| Order | Key | Source |
| --- | --- | --- |
| 1 | Organization | `X-API-Key` |
| 2 | Workspace | `X-Workspace-Id` or span attr |
| 3 | Call | `efficientai.call_short_id` (preferred) or header |

**Lookup:** `synthetic_call_traces` WHERE org + workspace + `call_short_id`. Failure → `correlated: false`.

| Layer | Failure if wrong |
| --- | --- |
| Organization | 401 |
| Workspace | Empty list / `correlated: false` |
| Call | Spans on wrong row if env var shared |

**Mental model:** OTel `trace_id` = internal; `call_short_id` = UI `#482931`.

### 10.2 Concurrent calls

| Concern | v1 | At scale |
| --- | --- | --- |
| 10–20 concurrent WebRTC | ✅ Unique IDs + workspace | Same |
| 100+ concurrent | ✅ Correlation valid | Watch row lock contention |
| Mixed spans in one batch | ✅ `group_spans_by_call_short_id()` | Same |
| Duplicate replay | ✅ Dedupe `(trace_id, span_id)` | Same |

---

## 11. Metrics — how numbers are calculated

### 11.1 Computation pipeline

| Stage | Module | Output |
| --- | --- | --- |
| Parse spans | `otlp_ingest.py` | Normalized span dicts |
| Group by turn | `otlp_mapper.py` | `stt/llm/tts_ttfb_ms`, `sut_response_latency_ms` |
| Call percentiles | `compute_trace_latency_summary()` | `response_latency_p50/p90/p95_ms` |
| Component percentiles | `compute_component_aggregates()` | Per-stage p50 on trace header |

Runs on **every ingest batch** (sync).

### 11.2 Per-turn field mapping

| Turn field | OTLP source | Conversion |
| --- | --- | --- |
| `stt_ttfb_ms` | `metrics.ttfb` on `stt` span | seconds × 1000 |
| `llm_ttfb_ms` | `metrics.ttfb` on `llm` span | same |
| `tts_ttfb_ms` | `metrics.ttfb` on `tts` span | same |
| `sut_response_latency_ms` | `turn.user_bot_latency_seconds` on `turn` span | end-to-end user→bot |

### 11.3 Percentile formula (p50, p90, p95)

1. Collect `sut_response_latency_ms` per turn (fallback: `s2s_ttfb_ms`, then `llm_ttfb_ms`)
2. Sort ascending
3. Index: `idx = min(n − 1, round((pct / 100) × (n − 1)))`
4. **Nearest-rank** — not linear interpolation

**Example — 4 turns:** `[800, 920, 1100, 1400]` → p50 = **1100 ms**, p90 = **1400 ms**.

### 11.4 What we compute vs providers

| Source | p50 in UI | Computed by us? |
| --- | --- | --- |
| OTLP / Pipecat | `response_latency_p50_ms` | **Yes** |
| Vapi playground | `turnLatency`, averages | **No** — provider JSON |
| Retell playground | `latency.*.p50` | **No** — provider histogram |
| Test Agent | Pipeline = OTLP; Analysis = evaluator | **Mixed** |

### 11.5 Provider-native metrics (playground Voice AI)

For Vapi/Retell/ElevenLabs/Smallest playground calls we **display provider fields** from `call_recordings.call_data` after `post_call_processing.py` polls the provider API. We do not recompute p50/p90 in our backend for these.

**Vapi** — source: `call_data.artifact.performanceMetrics`

| UI label | JSON field | Meaning |
| --- | --- | --- |
| Transcriber | `turnLatencies[].transcriberLatency` or `transcriberLatencyAverage` | STT time (ms) |
| Endpointing | `endpointingLatency` | Silence detection after user stops |
| LLM | `modelLatency` | Model response time |
| Voice (TTS) | `voiceLatency` | TTS generation time |
| Turn total | `turnLatency` | Provider-reported full turn time |

**Retell** — source: `call_data.latency` (provider histogram percentiles)

| UI label | JSON field |
| --- | --- |
| E2E p50 | `latency.e2e.p50` |
| ASR p50 | `latency.asr.p50` |
| LLM p50 | `latency.llm.p50` |
| TTS p50 | `latency.tts.p50` |

**Cost** — Vapi: `cost` or `costBreakdown.total` (stt/llm/tts/transport/vapi). Retell: `call_cost.combined_cost` + `call_cost.product_costs[]`.

**OTLP / Test Agent Pipeline tab** uses §11.1–11.3 only (`otlp_mapper.py`, `compute_trace_latency_summary()`).

---

## 12. Authentication & integration reference

### Required headers

| Header | Purpose |
| --- | --- |
| `X-API-Key` | Organization auth |
| `X-Workspace-Id` | Tenant isolation |
| `X-EfficientAI-Call-Short-Id` | Route OTLP batch (*or span attr*) |

### Key span attributes

| Attribute | Purpose |
| --- | --- |
| `efficientai.call_short_id` | Primary correlation |
| `gen_ai.operation.name` | `stt` / `llm` / `tts` / `s2s` |
| `metrics.ttfb` | TTFB in **seconds** (OTLP) |
| `turn.number` | Pipecat turn index |

### Customer onboarding (condensed)

```bash
uv pip install "pipecat-ai[...]>=1.4.0"
uv pip install -e '/path/to/efficientAI[otel]'
```

```bash
EFFICIENTAI_API_KEY=<key>
EFFICIENTAI_WORKSPACE_ID=<workspace-uuid>
EFFICIENTAI_API_BASE=https://staging.efficientai.cloud
```

**Three SDK hooks:** `ensure_trace_session()` → `setup_pipecat_worker_tracing()` → `close_trace_session()`.

Example: `docs/examples/pipecat_multi_agent_webrtc_tracing.py`

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| No traces in UI | Wrong workspace / API key | Verify headers; refresh |
| `correlated: false` | Missing `call_short_id` | `ensure_trace_session()` before export |
| Spans on wrong call | Shared `EFFICIENTAI_CALL_SHORT_ID` in env | Mint per call only |
| Trace stays `open` | No close + idle < 120s | `close_trace_session()` on disconnect |
| Empty turns | Tracing disabled | `enable_tracing=True` on PipelineWorker |
| Playground in Calls hub | Should not appear | Only `source=webhook` in observability list |

---

## 14. Deployment checklist (pilots)

1. Customer sets `EFFICIENTAI_API_KEY`, `EFFICIENTAI_WORKSPACE_ID`, `EFFICIENTAI_API_BASE`
2. Bot calls `ensure_trace_session()` at call start — never hardcode Call ID in env
3. `PipelineWorker(enable_tracing=True)` + `setup_pipecat_worker_tracing()`
4. `close_trace_session()` on disconnect (or rely on 120s idle close)
5. Verify in staging UI: `/observability/calls` → traces tab
6. For sales demos: use **separate workspace** for local vs staging
7. Before enterprise pitch: read §5 throughput table — quote **10–20 concurrent** for v1

---

## 15. Code module map

| Module | Responsibility |
| --- | --- |
| `app/api/v1/routes/synthetic_traces.py` | OTLP ingest, sessions, list, detail |
| `app/api/v1/routes/observability.py` | Webhook calls, SSE, evaluate |
| `app/services/synthetic_traces/trace_service.py` | Open/close traces, ingest, percentiles |
| `app/services/synthetic_traces/otlp_mapper.py` | Spans → turns |
| `app/services/synthetic_traces/otlp_ingest.py` | OTLP JSON + Protobuf parse |
| `app/services/voice_agent/playground_tracing.py` | Test Agent span stamping |
| `app/services/synthetic_traces/internal_otlp_exporter.py` | In-process export |
| `app/services/telephony/live_transcript_sse.py` | Poll-based SSE |
| `src/efficientai/integrations/efficientai_traces/` | Customer SDK |
| `frontend/src/pages/test-insights/TestInsights.tsx` | Calls hub UI |

---

## 16. Related documentation

* [Voice Call Traces & Observability (Index)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/69959682)
* [Call Import Architecture & Scaling Guide](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/59899905)
* Repo: `docs/synthetic-call-traces-pipecat.md` (quick start)
