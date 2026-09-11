# TDD: Voice Call Traces & Observability (Index)

**Status:** Living documentation (Mar 2026)  
**Owner:** Platform / Voice Evals  
**Parent space:** [EAI Tech Docs](https://efficientai.atlassian.net/wiki/spaces/ETD/overview)

---

## What this folder is

Technical design documentation for **voice call observability** in EfficientAI: OTLP ingest, production webhook calls, unified Calls hub UI, latency/cost measurement, and playground routing.

**Start here** for the big picture, then open the doc that matches your role.

---

## Documents

| Document | Who should read it | What it covers |
| --- | --- | --- |
| [TDD: Call Traces (Pipecat OTLP Observability)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/68616193) | Backend, SRE, frontend, sales/solutions | Architecture, OTLP ingest, drawer routing, provider vs OTLP metrics |
| [TDD: Call Traces — Scaling & Bottlenecks](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/72417282) | Platform, SRE, architects | **SaaS-scale capacity**, bottleneck map, gRPC/collector path, Prometheus/Tempo comparison, Phase 3–4 options |
| [Call Traces: Latency Metrics Explained](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/71434241) | Everyone — support, sales, customers | **Plain-language p50/p90/p95**, Listen/Think/Speak, formulas, examples, customer FAQ |
| [Pipecat quick start](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/68616193) (repo) | Customer engineers | SDK hooks, env vars, local WebRTC — `docs/synthetic-call-traces-pipecat.md` |

**Style reference:** Same narrative as [Call Import Concurrency](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/48103425) and [Usage & Cost Tracking](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/63045633) — problem first, then solution, then deep sections.

---

## UI surfaces quick map

**Canonical route:** `/observability/calls` (nav label: **Calls**)

| Surface | Route | Detail UI | Primary metrics source |
| --- | --- | --- | --- |
| **Calls hub — OTLP tab** | `/observability/calls` | `SyntheticCallTracePanel` drawer | `synthetic_call_traces` — we compute p50/p90 |
| **Calls hub — webhook tab** | `/observability/calls` | `ObservabilityCallDetailPanel` | Provider `call_data` (Vapi/Retell/etc.) |
| **Playground → Test Agent** | `/playground` | `/playground/test-agent-results/:id` | Evaluator + OTLP Pipeline tab |
| **Playground → Voice AI** | `/playground` | `/playground/call-recordings/:id` | Provider `call_data` |
| **Evaluator results** | `/evaluators/results/:id` | Routed drawer (`call_recording_source`) | Mixed — see main TDD §8 |

**Deep links on Calls hub:**

| Query param | Opens |
| --- | --- |
| `?trace={uuid}` | OTLP trace drawer |
| `?obs={call_short_id}` | Webhook call drawer |
| `?result={evaluator_result_id}` | Evaluator call drawer |

**Important:** Playground recordings (`source=playground`) are **not** listed in the production Calls hub.

---

## Metrics at a glance

| Source | Median / p50 in UI | Computed by us? |
| --- | --- | --- |
| **OTLP / Pipecat** | `response_latency_p50_ms` | **Yes** — [Latency Metrics Explained](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/71434241) |
| **Vapi playground** | `turnLatency`, `*LatencyAverage` | **No** — provider fields |
| **Retell playground** | `latency.*.p50` | **No** — provider histogram |
| **Test Agent** | Pipeline = OTLP; Analysis = evaluator | **Mixed** |

---

## Scaling at a glance (sales FAQ)

| Question | Short answer | Details |
| --- | --- | --- |
| How many concurrent OTLP calls today? | **100–500** with worker scale (Phase 2) | [Scaling TDD](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/72417282) §3 |
| What limits us at SaaS scale? | Postgres writes + derive CPU (not API) | Scaling TDD §4 |
| What unlocks 2,000+ concurrent? | OTel Collector gRPC + PG tune (Phase 3) | Scaling TDD §6 |
| What unlocks 10,000+ concurrent? | ClickHouse cluster + OTel Collector (Phase 3–4) | Scaling TDD §6 · [Storage Decision](call-traces-storage-decision-tdd-confluence.md) |
| Are traces sharded? | **No** — catalog Postgres only today | Scaling TDD §6.1 |
| Auto-close idle traces? | **120 seconds** after last span | Main TDD §6 |

---

## Repo doc mirrors (for PRs)

| Confluence | Local markdown | Fumadocs |
| --- | --- | --- |
| This index | `docs/call-traces-tdd-index-confluence.md` | `/docs/monitoring/call-traces/` |
| Call Traces TDD (architecture) | `docs/synthetic-call-traces-tdd-confluence.md` | `/docs/monitoring/call-traces/architecture/` |
| Call Traces Scaling TDD | `docs/call-traces-scaling-tdd-confluence.md` | — |
| Latency metrics (p50/p90/p95) | `docs/call-traces-latency-metrics-confluence.md` | `/docs/monitoring/call-traces/latency-metrics/` |
| Pipecat quick start | `docs/synthetic-call-traces-pipecat.md` | `/docs/monitoring/call-traces/pipecat-integration/` |

---

## Related (outside this folder)

- [Call Import Architecture & Scaling Guide](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/59899905)
- [Voice Playground user guide](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/44007425)
- [Usage & Cost Tracking](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/63045633)
