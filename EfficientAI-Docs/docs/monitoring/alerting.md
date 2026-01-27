---
id: alerting
title: Alerting
sidebar_position: 2
---

# Alerting

## What is Alerting?

**Alerting** lets you set up automated notifications when your Voice AI metrics cross certain thresholds.

Instead of manually checking dashboards, you can configure alerts to notify you via email or webhook (Slack, etc.) when something needs attention.

---

## Creating an Alert

An alert is defined by:

1. **Metric**: What are you measuring?
2. **Condition**: When should it trigger?
3. **Notification**: How should you be notified?

---

## Available Metrics

| Metric | Description |
|--------|-------------|
| **Number of Calls** | Total call count |
| **Call Duration** | Average or total call length |
| **Error Rate** | Percentage of failed calls |
| **Success Rate** | Percentage of successful calls |
| **Latency** | Response time |
| **Custom** | Your own defined metrics |

---

## Aggregation Types

How the metric is calculated over the time window:

| Aggregation | Description |
|-------------|-------------|
| **Sum** | Total value |
| **Average** | Mean value |
| **Count** | Number of occurrences |
| **Min** | Minimum value |
| **Max** | Maximum value |

---

## Operators

| Operator | Meaning |
|----------|---------|
| `>` | Greater than |
| `<` | Less than |
| `>=` | Greater than or equal |
| `<=` | Less than or equal |
| `=` | Equal to |
| `!=` | Not equal to |

---

## Example Alert

> "Alert me when the **average latency** is **greater than 500ms** in the last **60 minutes**"

Configuration:
- **Metric**: Latency
- **Aggregation**: Average
- **Operator**: >
- **Threshold**: 500
- **Time Window**: 60 minutes

---

## Notification Options

### Email
Add one or more email addresses to receive alert notifications.

### Webhooks
Send alerts to Slack, Discord, or any webhook-compatible service.

Example Slack webhook:
```
https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXX
```

---

## Notification Frequency

Control how often you receive notifications:

| Frequency | Description |
|-----------|-------------|
| **Immediate** | Send as soon as triggered |
| **Hourly** | Batch notifications hourly |
| **Daily** | Daily digest |
| **Weekly** | Weekly summary |

---

## Alert Status

| Status | Description |
|--------|-------------|
| **Active** | Alert is monitoring and will trigger |
| **Paused** | Alert is temporarily disabled |
| **Disabled** | Alert is turned off |

---

## Alert History

When an alert is triggered, a history record is created with:
- Trigger timestamp
- Metric value at trigger
- Acknowledgement status
- Resolution notes

View alert history in the Alerts dashboard to track incidents over time.
