# TDD: Voice Call Traces & Observability (Index)

**Status:** Living documentation (Mar 2026)  
**Owner:** Platform / Voice Evals  
**Parent space:** [EAI Tech Docs](https://efficientai.atlassian.net/wiki/spaces/ETD/overview)

---

## What this folder is

This folder groups **all technical design docs** for voice call observability in EfficientAI: how we ingest traces, show call details, measure latency/cost, and route the UI across playground, evaluator, and observability surfaces.

Read the **index table** below first, then open the doc that matches your question.

---

## Documents in this folder

| # | Document | Who should read it | What it covers |
| --- | --- | --- | --- |
| **1** | [TDD: Call Traces (Pipecat OTLP Observability)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/68616193) | Backend, integrations, Pipecat customers | **OTLP ingest** — session minting, span correlation, turn mapping, **p50/p90/p95 math**, customer SDK, Call Traces list UI |
| **2** | [TDD: Call Details & Unified Traces (End-to-End)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/69763074) | Frontend, full-stack, PMs | **UI & playback** — drawer routing, waveform/audio, provider timelines, Test Agent vs Voice AI result pages, cost/latency tabs |

### How the two docs relate

```
                    ┌─────────────────────────────────────┐
                    │  Doc 1: OTLP / Pipecat Traces       │
                    │  (customer bots → spans → turns)    │
                    └──────────────┬──────────────────────┘
                                   │ same turn rows + p50/p90
                                   ▼
┌──────────────────┐    ┌─────────────────────────────────────┐
│ Provider webhooks│───►│  Doc 2: Call Details (End-to-End)   │
│ Vapi/Retell/etc. │    │  (one drawer, four data sources)    │
└──────────────────┘    └─────────────────────────────────────┘
```

- **Doc 1** is **not** a prerequisite to read Doc 2, but Doc 2 references Doc 1 for OTLP-specific metrics.
- **Doc 2** is the continuation for anyone asking: *"User clicked a row — what API fires and how is latency shown?"*
- **Doc 1** answers: *"Customer Pipecat bot exports spans — how do we store and aggregate them?"*

---

## UI surfaces quick map (where results appear)

There are **two playground result experiences** plus evaluator and observability:

| Surface | Route | Tab / entry | Detail UI | Primary metrics source |
| --- | --- | --- | --- | --- |
| **Playground → Test Agent** | `/playground` | **Test Agents** tab → row click | Full page `/playground/test-agent-results/:id` **or** drawer (`EvaluatorCallDetailPanel`) | `evaluator_results` + optional OTLP trace (`SyntheticCallTracePanel` Pipeline tab) |
| **Playground → Voice AI** | `/playground` | **Voice AI Agents** tab → row click | Drawer only (`ProviderCallTracePanel`) | Provider `call_data` (Vapi/Retell/ElevenLabs/Smallest) |
| **Evaluator results** | `/evaluators/results/:id` | Call details button | Routed drawer (playground vs webhook vs evaluator) | Mixed — see Doc 2 §5 |
| **Call Traces (OTLP)** | `/call-traces` | Row click | `SyntheticCallTracePanel` drawer | `synthetic_call_traces` — see Doc 1 §9 (metrics) |
| **Observability calls** | `/calls` | Row click | `ObservabilityCallDetailPanel` | Webhook `call_recordings` + provider fields |

**Important:** Test Agent and Voice AI are **separate tabs** in Agent Playground (`AgentPlayground.tsx`). They use **different drawers** and **different APIs** even though both show a 6-digit Call ID.

---

## Metrics at a glance (where p50/p90 come from)

| Source | Median / p50 shown in UI | Computed by us? |
| --- | --- | --- |
| **OTLP / Pipecat traces** | `response_latency_p50_ms` on trace header; component `p50` in aggregates | **Yes** — from per-turn `sut_response_latency_ms` (Doc 1 §9) |
| **Vapi playground calls** | Per-turn `turnLatency`, session `*LatencyAverage` | **No** — from Vapi `artifact.performanceMetrics` (Doc 2 §9) |
| **Retell playground calls** | `latency.e2e/asr/llm/tts` p50 fields | **No** — from Retell API payload (Doc 2 §9) |
| **Test Agent evaluator run** | Pipeline tab uses OTLP turns; Analysis tab uses evaluator metrics | **Mixed** |

For the **exact percentile formula** and worked examples, see **Doc 1 §9 — Latency metrics & percentiles**.

---

## Repo doc mirrors (for PRs)

| Confluence | Local markdown |
| --- | --- |
| This index | `docs/call-traces-tdd-index-confluence.md` |
| Doc 1 OTLP | `docs/synthetic-call-traces-tdd-confluence.md` |
| Doc 2 Call Details | `docs/call-details-unified-traces-tdd-confluence.md` |

---

## Related (outside this folder)

- [Voice Playground user guide](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/44007425)
- [Usage & Cost Tracking](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/63045633)
