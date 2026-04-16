---
id: metrics
title: Metrics
sidebar_position: 5
---

# Metrics

Metrics are the explicit scoring rules used to evaluate each call.

## Metric selection is explicit

Only metrics that are **enabled** for your organization are evaluated.

This means run scoring always reflects your currently enabled metric set, not a hidden global default.

## Metric groups

EfficientAI evaluates three practical metric groups:

### 1) LLM-evaluated conversation metrics

Examples:

- Follow Instructions
- Professionalism
- Problem Resolution

Method:

- Evaluates transcript and context against metric definitions.

### 2) Acoustic metrics (signal-based)

Examples:

- Pitch Variance
- Jitter
- Shimmer
- HNR

Method:

- Computed from recorded audio signal characteristics.

### 3) AI voice quality metrics (model-based audio quality)

Examples:

- MOS Score
- Emotion Category
- Emotion Confidence
- Valence
- Arousal
- Speaker Consistency
- Prosody Score

Method:

- Uses audio-based ML evaluation for quality, emotion, and consistency.

## Default behavior notes

By default:

- `Pitch Variance` starts enabled.
- `Jitter`, `Shimmer`, and `HNR` start disabled.

You can enable or disable metrics from the Metrics page at any time.

## How metrics are applied during processing

1. Call audio and transcript are collected.
2. Enabled metrics are split by evaluation method.
3. Audio-required metrics run only when audio is available.
4. LLM metrics run on transcript and context.
5. Scores are written to evaluator results for reporting and comparison.

If audio is missing, audio-dependent metrics are skipped instead of being fabricated.
