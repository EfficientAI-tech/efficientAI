# Call Traces overview

**Call Traces** show per-turn **Listen → Think → Speak** timing, transcripts, and call-level latency percentiles (p50 / p90 / p95) for voice agents — without running your own observability stack.

Use this section to understand where traces appear in the UI, how metrics are computed, and how to connect a Pipecat (or other OTLP) voice agent.

---

## Start here

| Guide | Who should read it | What it covers |
| --- | --- | --- |
| Latency metrics explained | Everyone — support, sales, customers | Plain-language **p50 / p90 / p95**, Listen / Think / Speak, formulas, examples, FAQ |
| Architecture & scaling | Engineers, SRE, solutions | OTLP ingest, ClickHouse + S3, Calls hub routing, capacity |
| Pipecat & OTLP integration | Customer engineers | SDK hooks, env vars, WebRTC quick start, API reference |

Related: **Calls (webhooks)** — production call ingest via Vapi, Retell, or custom webhooks (separate from OTLP traces).

---

## What Call Traces are

During a voice call, EfficientAI:

1. Assigns a **6-digit Call ID** (`call_short_id`, shown as `#482931` in the UI).
2. Ingests **OpenTelemetry spans** from your voice agent (Pipecat, LiveKit with OTLP export, or in-process from the Test Agent playground).
3. Groups spans into **turn rows**, computes **p50 / p90 / p95**, and shows a **waterfall** in the Calls hub.

**What this release does not include**

- Dollar cost from OTLP spans (cost still comes from provider `call_data` on webhook calls).
- Customer-managed OTel Collector sidecars (you can still point any OTLP HTTP exporter at our endpoint).

---

## UI surfaces

**Canonical route:** `/observability/calls` (sidebar: **Calls**)

| Surface | Route | Detail view | Metrics source |
| --- | --- | --- | --- |
| **Calls hub — Traces tab** | `/observability/calls` | Pipeline trace drawer | EfficientAI computes p50 / p90 / p95 |
| **Calls hub — Calls tab** | `/observability/calls` | Webhook call drawer | Provider `call_data` (Vapi / Retell / etc.) |
| **Playground → Test Agent** | `/playground` | Test agent result + Pipeline tab | Evaluator + OTLP |
| **Playground → Voice AI** | `/playground` | Call recording detail | Provider `call_data` |

**Deep links on Calls hub:**

| Query param | Opens |
| --- | --- |
| `?trace={uuid}` | OTLP trace drawer |
| `?obs={call_short_id}` | Webhook call drawer |
| `?result={evaluator_result_id}` | Evaluator call drawer |

**Playground isolation:** Playground recordings (`source=playground`) are **not** listed in the production Calls hub. Only webhook production calls and OTLP traces appear there.

---

## Metrics at a glance

| Source | Median / p50 in UI | Computed by EfficientAI? |
| --- | --- | --- |
| **OTLP / Pipecat** | `response_latency_p50_ms` | **Yes** — see Latency metrics |
| **Vapi playground** | `turnLatency`, `*LatencyAverage` | **No** — provider fields |
| **Retell playground** | `latency.*.p50` | **No** — provider histogram |
| **Test Agent** | Pipeline = OTLP; Analysis = evaluator | **Mixed** |

**Rule of thumb:** If the drawer says **Pipeline** or **OTLP**, our percentile math applies. If it shows **Vapi / Retell / provider metrics**, use the vendor's definitions.

---

## Scaling FAQ (short)

| Question | Short answer |
| --- | --- |
| How many concurrent OTLP calls? | **~100–500+** per workspace with ClickHouse + `worker-traces` and deferred ingest (staging targets); tune rate limits and CH capacity for your tenant mix |
| What limits us at extreme scale? | ClickHouse insert/query capacity, S3 WAL backlog, Redis/Celery queue depth — not Postgres span JSONB |
| Where are spans stored? | **ClickHouse** (list/detail/spans); **S3** for ingest WAL batches and optional span archives |
| Is Postgres still involved? | **Yes** — org/workspace auth, evaluator links (`synthetic_call_trace_id` UUID), call recordings metadata — **not** raw span payloads at scale |
| Auto-close idle traces? | **120 seconds** after last span |

Details: Architecture & scaling.

---

## API prefix

Voice agents export spans to:

```
POST {EFFICIENTAI_API_BASE}/api/v1/observability/traces
```

Session lifecycle:

- `POST /api/v1/observability/traces/sessions`
- `POST /api/v1/observability/traces/sessions/{call_short_id}/close`

Setup helper (returns `.env` block and snippets for the active workspace):

```
GET /api/v1/observability/traces/setup
```

Full integration steps: Pipecat & OTLP integration.
