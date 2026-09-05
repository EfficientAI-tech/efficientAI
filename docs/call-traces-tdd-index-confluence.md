# TDD: Voice Call Traces & Observability (Index)

**Status:** Living documentation (Mar 2026)  
**Owner:** Platform / Voice Evals  
**Parent space:** [EAI Tech Docs](https://efficientai.atlassian.net/wiki/spaces/ETD/overview)

---

## What this folder is

Technical design documentation for **voice call observability** in EfficientAI: OTLP ingest, production webhook calls, unified Calls hub UI, latency/cost measurement, and playground routing.

**Start here** if you need the big picture. Open the doc that matches your role.

---

## Documents in this folder

| # | Document | Who should read it | What it covers |
| --- | --- | --- | --- |
| **1** | [TDD: Call Traces (Pipecat OTLP Observability)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/68616193) | Backend, SRE, sales/solutions | **Problem → solution → architecture** — OTLP ingest, scaling tables, metrics math |
| **2** | [TDD: Call Details & Unified Traces (UI)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/69763074) | Frontend, full-stack, PMs | **UI** — `/observability/calls`, drawer routing, waveform/audio, provider timelines, Test Agent vs Voice AI |

**Style reference:** Same narrative as [Call Import Concurrency](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/48103425) and [Usage & Cost Tracking](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/63045633) — problem first, then solution, then deep sections.

### How the two docs relate

```
                    ┌──────────────────────────────────────────┐
                    │  Doc 1: Architecture & Scaling           │
                    │  OTLP ingest, webhooks, Postgres, p50    │
                    └────────────────────┬─────────────────────┘
                                         │ same turn rows + metrics
                                         ▼
┌──────────────────┐         ┌──────────────────────────────────────────┐
│ Provider webhooks│────────►│  Doc 2: Call Details (UI)                │
│ Pipecat OTLP     │         │  Drawers, audio, Calls hub, deep links   │
└──────────────────┘         └──────────────────────────────────────────┘
```

---

## UI surfaces quick map

**Canonical route:** `/observability/calls` (nav label: **Calls**)

| Surface | Route | Detail UI | Primary metrics source |
| --- | --- | --- | --- |
| **Calls hub — OTLP tab** | `/observability/calls` | `SyntheticCallTracePanel` drawer | `synthetic_call_traces` — we compute p50/p90 |
| **Calls hub — webhook tab** | `/observability/calls` | `ObservabilityCallDetailPanel` | Provider `call_data` (Vapi/Retell/etc.) |
| **Playground → Test Agent** | `/playground` | `/playground/test-agent-results/:id` | Evaluator + OTLP Pipeline tab |
| **Playground → Voice AI** | `/playground` | `/playground/call-recordings/:id` | Provider `call_data` |
| **Evaluator results** | `/evaluators/results/:id` | Routed drawer | Mixed — see Doc 2 §5 |

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
| **OTLP / Pipecat** | `response_latency_p50_ms` | **Yes** — Doc 1 §11 |
| **Vapi playground** | `turnLatency`, `*LatencyAverage` | **No** — provider fields |
| **Retell playground** | `latency.*.p50` | **No** — provider histogram |
| **Test Agent** | Pipeline = OTLP; Analysis = evaluator | **Mixed** |

---

## Scaling at a glance (sales FAQ)

| Question | Short answer | Details |
| --- | --- | --- |
| How many concurrent OTLP calls today? | **10–20** comfortably on staging | Doc 1 §5.1 |
| What limits us? | Sync ingest + JSONB span rewrite | Doc 1 §5.5 |
| What unlocks 500+ concurrent? | Async Celery ingest + S3 spans | Doc 1 §5.4 Phase 2 |
| Are traces sharded? | **No** — catalog Postgres only | Doc 1 §3 |
| Auto-close idle traces? | **120 seconds** after last span | Doc 1 §6 |

---

## Repo doc mirrors (for PRs)

| Confluence | Local markdown |
| --- | --- |
| This index | `docs/call-traces-tdd-index-confluence.md` |
| Doc 1 — OTLP / architecture | `docs/synthetic-call-traces-tdd-confluence.md` |
| Doc 2 — Call details UI | `docs/call-details-unified-traces-tdd-confluence.md` |
| Pipecat quick start | `docs/synthetic-call-traces-pipecat.md` |

---

## Related (outside this folder)

- [Call Import Architecture & Scaling Guide](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/59899905)
- [Voice Playground user guide](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/44007425)
- [Usage & Cost Tracking](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/63045633)
