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
| [TDD: Call Traces (Pipecat OTLP Observability)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/68616193) | Backend, SRE, frontend, sales/solutions | Architecture, scaling, OTLP ingest, drawer routing, **p50/p90/p95 math**, provider vs OTLP metrics |
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
| **OTLP / Pipecat** | `response_latency_p50_ms` | **Yes** — main TDD §11 |
| **Vapi playground** | `turnLatency`, `*LatencyAverage` | **No** — provider fields |
| **Retell playground** | `latency.*.p50` | **No** — provider histogram |
| **Test Agent** | Pipeline = OTLP; Analysis = evaluator | **Mixed** |

---

## Scaling at a glance (sales FAQ)

| Question | Short answer | Details |
| --- | --- | --- |
| How many concurrent OTLP calls today? | **10–20** comfortably on staging | Main TDD §5.1 |
| What limits us? | Sync ingest + JSONB span rewrite | Main TDD §5.5 |
| What unlocks 500+ concurrent? | Async Celery ingest + S3 spans | Main TDD §5.4 Phase 2 |
| Are traces sharded? | **No** — catalog Postgres only | Main TDD §3 |
| Auto-close idle traces? | **120 seconds** after last span | Main TDD §6 |

---

## Repo doc mirrors (for PRs)

| Confluence | Local markdown |
| --- | --- |
| This index | `docs/call-traces-tdd-index-confluence.md` |
| Call Traces TDD (architecture) | `docs/synthetic-call-traces-tdd-confluence.md` |
| Pipecat quick start | `docs/synthetic-call-traces-pipecat.md` |

---

## Related (outside this folder)

- [Call Import Architecture & Scaling Guide](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/59899905)
- [Voice Playground user guide](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/44007425)
- [Usage & Cost Tracking](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/63045633)
