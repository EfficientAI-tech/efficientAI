# Call Traces: Latency Metrics Explained (p50, p90, p95)

**Status:** Living documentation (Mar 2026)  
**Owner:** Platform / Voice Evals  
**Audience:** Everyone — engineers, support, sales, and customers  
**Parent folder:** [TDD: Voice Call Traces & Observability (Index)](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/69959682)

**Related (technical deep dive):** [TDD: Call Traces — Pipecat OTLP Observability](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/68616193) §11

---

## 1. Why we measure latency

When someone talks to a voice AI agent, they notice **how long it takes to get a reply**.

- Too slow → the call feels broken or awkward.
- Fast and consistent → the call feels natural.

EfficientAI records each call as a **trace** and breaks it into **turns** (one back-and-forth: user speaks, agent replies).

We show two kinds of numbers:

| Kind | Plain English | Example labels in UI |
| --- | --- | --- |
| **Per-turn** | How long *this one* reply took | Turn table, waterfall bars |
| **Call summary** | How the *whole call* behaved on average and at the tail | **Response p50**, **p90**, **p95** in the header |

This doc explains **what those summary numbers mean**, **how we calculate them**, and **what to tell customers**.

---

## 2. The three pipeline stages (Listen → Think → Speak)

Most voice agents run in three steps:

```
User speaks  →  [Listen]  →  [Think]  →  [Speak]  →  Agent audio plays
                 (STT)        (LLM)        (TTS)
```

| UI label | Technical name | What it measures |
| --- | --- | --- |
| **Listen** | STT (speech-to-text) | Time until we have the user's words |
| **Think** | LLM (language model) | Time until the model starts its answer |
| **Speak** | TTS (text-to-speech) | Time until the agent's voice starts playing |

Each stage has a **TTFB** value — **Time To First Byte** — in milliseconds:

- `stt_ttfb_ms` → Listen
- `llm_ttfb_ms` → Think
- `tts_ttfb_ms` → Speak

**Important:** These three numbers are **not always additive**. The pipeline can overlap work (e.g. streaming). So **Listen + Think + Speak ≠ Response latency** in general.

---

## 3. Response latency (the number customers care about most)

**Response latency** = *how long the caller waited for the agent to start responding* after they spoke.

In our data model this is `sut_response_latency_ms` (**SUT** = system under test, i.e. your voice agent).

### Where it comes from (best → fallback)

| Priority | Source | Meaning |
| --- | --- | --- |
| 1 (best) | Pipecat `turn.user_bot_latency_seconds` on the `turn` span | Measured end-to-end by the voice framework |
| 2 | Sum of Listen + Think + Speak when all three exist and user spoke | Derived estimate |
| 3 | Think (LLM) only | Partial fallback when other data is missing |

We **prefer measured end-to-end** over adding components.

### What you see in the UI

| UI label | Field | What it is |
| --- | --- | --- |
| **Response p50** | `response_latency_p50_ms` | Typical reply time for this call |
| **Response p90** | `response_latency_p90_ms` | Slower replies — 9 out of 10 turns were this fast or faster |
| **Response p95** | `response_latency_p95_ms` | Tail latency — 19 out of 20 turns were this fast or faster |
| **"13 of 14 turns"** | `response_latency_sample_count` | How many turns were used in the math (see §6) |

Stage headers (Listen / Think / Speak p50) use the same percentile math but only on that stage's TTFB values.

---

## 4. Percentiles explained simply (p50, p90, p95)

### One number: average vs median

| Stat | Kid-friendly analogy | Problem |
| --- | --- | --- |
| **Average** | "Add all wait times and divide" | One very slow turn pulls the average up — feels unfair |
| **Median (p50)** | "Sort all waits; pick the middle one" | Ignores one-off spikes in the *typical* number |
| **p90 / p95** | "How bad was it for the slowest 10% / 5%?" | Shows tail pain without one outlier dominating |

We use **percentiles**, not averages, for call summaries.

### What p50, p90, p95 mean

| Label | Also called | Plain English |
| --- | --- | --- |
| **p50** | Median | Half the turns were **this fast or faster** |
| **p90** | 90th percentile | 90% of turns were **this fast or faster** (only 10% were slower) |
| **p95** | 95th percentile | 95% of turns were **this fast or faster** (only 5% were slower) |

**Example call with 10 turns** (response times in ms):

```
[600, 700, 750, 800, 850, 900, 950, 1100, 1500, 3000]
```

- **p50 ≈ 875 ms** — a typical turn
- **p90 ≈ 1500 ms** — most turns were under ~1.5 s; one was much worse
- **p95 ≈ 3000 ms** — the very slowest turns live here

Customers often care about **p50** ("does it usually feel snappy?") and **p95** ("do we ever embarrass ourselves?").

---

## 5. The formula (how we actually compute it)

We use the **nearest-rank** method (same as the main architecture TDD §11.3).

### Steps

1. Collect one response latency per **eligible** turn (§6).
2. Sort the list **smallest → largest**.
3. Pick the index:

```
n = number of values
idx = min(n − 1, round((percent / 100) × (n − 1)))
answer = sorted_values[idx]
```

4. Round to **one decimal place** (e.g. `1100.0` ms).

We do **not** interpolate between two values — we pick an actual turn from the sorted list.

### Worked examples

#### What does the number we multiply by mean?

**It is not “number of turns minus one excluded.”** It is the **last array index** when positions start at 0.

| Symbol | Meaning |
| --- | --- |
| **n** | How many latency values are in the sorted list (after eligibility in §6) |
| **n − 1** | The index of the **last** value (arrays count from 0, not 1) |
| **idx** | Which slot we pick in the sorted list (0 = smallest, n−1 = largest) |

**Example A uses all 4 turns** — nothing is dropped in this step. Turn exclusion (e.g. “13 of 14 turns”) happens **earlier**, when we build the list. Percentile math only runs on whatever values are already in the list.

#### Example A — 4 values: `[800, 920, 1100, 1400]`

Here **n = 4**, so we multiply by **n − 1 = 3** (the last index is 3, not 4):

| Index (idx) | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| Value (ms) | 800 | 920 | 1100 | 1400 |
| Human label | 1st | 2nd | 3rd | 4th |

| Percentile | Calculation | idx picks | Result |
| --- | --- | --- | --- |
| p50 | round(0.5 × **3**) = **2** | 3rd value | **1100 ms** |
| p90 | round(0.9 × **3**) = **3** | 4th value | **1400 ms** |
| p95 | round(0.95 × **3**) = **3** | 4th value | **1400 ms** |

With only 4 samples, p90 and p95 both land on the slowest turn. More turns are needed for tail percentiles to differ.

#### Example B — 3 values: `[1200, 2400, 3600]`

Here **n = 3**, so multiply by **n − 1 = 2**:

| Index | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Value (ms) | 1200 | 2400 | 3600 |

| Percentile | Calculation | Result |
| --- | --- | --- |
| p50 | round(0.5 × **2**) = 1 → 2nd value | **2400 ms** |
| p90 | round(0.9 × **2**) = 2 → 3rd value | **3600 ms** |

#### Example C — 1 value only: `[850]`

Here **n = 1**, so **n − 1 = 0**. Every percentile uses index 0 → **850 ms**.

#### Quick reference: what to multiply by

| Values in list (n) | Multiply by (n − 1) | Last index |
| --- | --- | --- |
| 4 | **3** | 3 |
| 10 | **9** | 9 |
| 13 | **12** | 12 |
| 14 eligible turns | **13** | 13 |

### Listen / Think / Speak p50

Same formula, but the input list is all `stt_ttfb_ms` (or `llm` / `tts`) values from turns that have that stage — **not** filtered by the response-latency eligibility rules in §6.

---

## 6. Which turns count toward Response p50 / p90 / p95?

Not every row in the turn table is included. We only want turns that represent a **real user → agent exchange**.

### Included ✅

| Situation | Counts? |
| --- | --- |
| User spoke and agent replied (normal turn) | **Yes** |
| Agent greeting with **measured** end-to-end latency (`sut_measured_e2e`) | **Yes** |
| Speech-to-speech (S2S) mode with measured latency | **Yes** |

### Excluded ❌

| Situation | Why |
| --- | --- |
| Agent-only opener with **no** user speech and only LLM timing | Not a real "user waited for reply" sample |
| Turn with only partial LLM fallback (`sut_is_partial_fallback`) | Incomplete measurement |
| Turn with no response latency at all | Nothing to measure |

That's why you may see **"13 of 14 turns"** — 14 turns exist in the trace, but only 13 were valid samples for the header percentiles.

**UI hint text:** *"Uses turns where the user spoke and the agent replied. Agent-only greetings are not included."*

---

## 7. Turn states you might see (and what they mean)

| Badge / state | Meaning | Affects percentiles? |
| --- | --- | --- |
| **Incomplete** | Missing STT, LLM, or TTS data for that turn | Usually excluded if no valid response latency |
| **Interrupted** | User or agent cut the turn short | Included if we have a valid measured latency |
| **Talk-over** | User spoke while agent was still talking | Turn still counts if measured |
| **Opener** (Turn 1) | Bot greeting before user speaks | Often excluded unless end-to-end was measured |

**Turn numbering:** Pipecat Turn 1 is often the **greeting window**. The first real user message may show as Turn 2. This is expected — not a bug.

---

## 8. Per-turn vs call summary — don't mix them up

| Question | Look at |
| --- | --- |
| "How long did Turn 5 take?" | That turn's **Response** column (`sut_response_latency_ms`) |
| "Was this call generally fast?" | Header **Response p50** |
| "Did we have bad spikes?" | **p90 / p95** |
| "How fast is our STT provider?" | **Listen p50** (stage aggregate) |

**Waterfall bar length** = span duration on the timeline.  
**Table TTFB** = time to first byte for that component.  
They are related but **not always identical** — use TTFB for latency SLOs.

---

## 9. Where the numbers come from (OTLP vs provider)

| Call type | Who computes p50? | Notes |
| --- | --- | --- |
| **Calls hub → OTLP tab** | **EfficientAI** | This doc applies fully |
| **Test Agent → Pipeline tab** | **EfficientAI** | Same OTLP pipeline |
| **Playground → Voice AI (Vapi, Retell, etc.)** | **Provider** | We display their JSON — different field names |
| **Calls hub → Webhook tab** | **Provider** | Vapi `turnLatency`, Retell `latency.e2e.p50`, etc. |

**Sales rule of thumb:** If the drawer says **Pipeline** or **OTLP**, our p50 math in §4–§6 applies. If it says **Vapi / Retell / provider metrics**, cite the vendor's definitions.

---

## 10. Customer FAQ (copy-paste friendly)

**Q: What is p50?**  
A: The middle reply time — half the turns in the call were faster, half were slower.

**Q: Why not use average?**  
A: One very slow turn would skew an average. Percentiles show typical (p50) and worst-case tail (p95) more honestly.

**Q: Why does p50 not equal Listen + Think + Speak?**  
A: Response latency is measured end-to-end on the call timeline. Stages can overlap and streaming changes timing — we measure what the caller actually experienced.

**Q: Why "13 of 14 turns"?**  
A: We only include turns where the user spoke and we have a trustworthy reply measurement. Pure agent greetings without user speech are excluded.

**Q: Is this the same as your phone provider's latency?**  
A: Not always. We measure your **AI pipeline**. Network and telephony add extra delay that may not appear in OTLP traces.

**Q: Can I use this for billing or SLOs?**  
A: p50/p95 are great for **quality monitoring**. Billing uses separate cost fields (provider `call_data` or usage APIs).

---

## 11. Quick reference card

```
┌─────────────────────────────────────────────────────────────┐
│  CALL HEADER                                                │
│  Response p50 / p90 / p95  ← sut_response_latency_ms        │
│                            per eligible turn, then §5 formula│
│  "N of M turns"            ← eligible sample count          │
├─────────────────────────────────────────────────────────────┤
│  STAGE ROWS                                                 │
│  Listen p50  ← stt_ttfb_ms across turns with STT           │
│  Think p50   ← llm_ttfb_ms across turns with LLM          │
│  Speak p50   ← tts_ttfb_ms across turns with TTS          │
├─────────────────────────────────────────────────────────────┤
│  FORMULA                                                    │
│  sort values → idx = round(pct/100 × (n−1)) → pick value   │
│  round to 0.1 ms                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 12. Repo mirror

| Confluence | Local markdown |
| --- | --- |
| [This page](https://efficientai.atlassian.net/wiki/spaces/ETD/pages/71434241) | `docs/call-traces-latency-metrics-confluence.md` |

**Implementation (for engineers):**

- Backend: `app/services/synthetic_traces/otlp_mapper.py` — `latency_percentile()`, `response_latency_samples()`, `compute_trace_latency_summary()`
- Frontend: `frontend/src/lib/traceLatencySummary.ts` — mirrors eligibility + percentiles for live UI
