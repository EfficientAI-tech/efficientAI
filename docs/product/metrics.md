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
1.  **Hard Numbers**: Things like "How fast did it answer?" (Latency) or "Did it mishear any words?" (Accuracy).
2.  **Quality Scores**: Did the AI sound friendly? Did it solve the customer's problem?

You check these metrics to see if your AI is ready for the real world.

---

## Technical Details

Metrics are the quantitative and qualitative measurements used to assess performance.

### Technical Metrics (Quantitative)

These are calculated automatically by the `MetricsService`:

*   **Word Error Rate (WER)**: Accuracy of the Agent's speech recognition. calculated by comparing what was said vs. what was transcribed. 0.0 is perfect; higher is worse.
*   **Character Error Rate (CER)**: Similar to WER but at the character level.
*   **Latency**: How long the system takes to process inputs (in milliseconds).
*   **Real-Time Factor (RTF)**: `Processing Time / Audio Duration`. Needs to be `< 1.0` for real-time performance.

### Custom Metrics (Qualitative)

You can define custom metrics (like "Empathy" or "Resolution Success") which can be rated on a scale (Type: `rating`) or as a pass/fail (Type: `boolean`).

### Storage

Metric results are stored in the JSON `metric_scores` column of the `EvaluatorResult` database table.
