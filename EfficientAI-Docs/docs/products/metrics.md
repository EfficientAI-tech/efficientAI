---
id: metrics
title: Metrics
sidebar_position: 5
---

# Metrics

## What are Metrics?

**Metrics** are the "Grades" or "Scorecards" for your AI.

After a test call finishes, you want to know how well it went. EfficientAI answers this with data.

We give you two types of grades:
1.  **Quantitative Metrics**: Hard numbers like latency, speaking rate, and voice quality measurements.
2.  **Qualitative Metrics**: Subjective scores like how human the AI sounds or emotional accuracy.

---

## Quantitative Metrics

These are calculated automatically from the audio and conversation data:

| Metric | Description |
|--------|-------------|
| **E2E Latency** | End-to-end response time — how fast the AI responds |
| **Pitch Variance** | Voice pitch variation analysis |
| **Jitter & Shimmer** | Voice quality fluctuations — stability of the voice |
| **Speaking Rate (WPM)** | Words per minute — conversation pacing |
| **Interruption Gap** | Time between speaker turns |
| **HNR** | Harmonics-to-Noise Ratio — voice clarity measurement |
| **Turn Taking** | Speaker transition patterns and timing |
| **Barge-In Interruption** | Detection of when speakers talk over each other |
| **Silence Duration** | Length and frequency of pauses |

### How They Work

Quantitative metrics are computed by analyzing:
- Audio waveforms (for pitch, jitter, shimmer, HNR)
- Timestamps (for latency, turn taking, gaps)
- Transcriptions (for speaking rate)

---

## Qualitative Metrics

These are evaluated using LLM analysis of the conversation:

| Metric | Description |
|--------|-------------|
| **Human Likeness (HPDR-5)** | How natural and human the AI sounds |
| **MOS** | Mean Opinion Score — overall quality rating |
| **Emotional Match Accuracy** | How well the AI matches appropriate emotions |
| **Valence/Arousal** | Emotional intensity and positivity analysis |
| **Prosody Expressiveness** | Speech rhythm, intonation, and expression quality |
| **Speaker Consistency** | Voice consistency across the conversation |

### How They Work

Qualitative metrics use an LLM to analyze the conversation transcript and audio characteristics, providing subjective assessments that would normally require human evaluation.

---

## Custom Metrics

You can define your own custom metrics for specific use cases:

- **Rating Type**: Score on a scale (e.g., 1-5)
- **Boolean Type**: Pass/fail assessment

### Examples
- "Resolution Success" — Did the AI solve the customer's problem?
- "Empathy Score" — Was the AI appropriately empathetic?
- "Upsell Attempted" — Did the AI try to upsell?

---

## Storage

Metric results are stored in the `metric_scores` JSON column of the `EvaluatorResult` database table and can be viewed in the Results Dashboard.
