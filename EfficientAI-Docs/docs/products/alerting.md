---
id: alerting
title: Alerting
sidebar_position: 6
---

# Alerting

## What is Alerting?

**Alerting** lets you set up automatic notifications when something important happens with your voice AI agents. Instead of manually checking dashboards, you define rules — and EfficientAI will notify you via **Slack**, **email**, or both when those rules are triggered.

Think of it as a smoke detector for your voice AI operations. You tell it what to watch (e.g., "error rate is above 10%"), and it will ring the alarm when something goes wrong.

### Quick Example

> "If the **average latency** of my Customer Support Agent exceeds **3 seconds** over the last **30 minutes**, send a Slack notification to #ops-alerts."

That's it — one alert rule, and you'll never miss a latency spike again.

---

## Key Concepts

### Alert

An **Alert** is a monitoring rule. It defines:
- **What** to measure (metric + aggregation)
- **When** to fire (threshold + operator)
- **How far back** to look (time window)
- **Who** to notify (emails + webhooks)
- **How often** to notify (frequency / cooldown)

### Alert History

Every time an alert's condition is met and fires, an **Alert History** record is created. This gives you a full audit trail of when alerts were triggered, what the value was, and whether notifications were sent.

---

## Setting Up an Alert

### Step 1: Navigate to Alerts

From the sidebar, go to **Alerting > Alerts**. You'll see a list of all configured alerts.

### Step 2: Create a New Alert

Click **Create Alert** and fill in the following:

#### Basic Information

| Field | Required | Description |
|---|---|---|
| **Alert Name** | Yes | A descriptive name, e.g., "High Error Rate - Production" |
| **Description** | No | Optional notes about what this alert monitors |

#### Metric Condition

This is the core of your alert — the rule that determines when it fires.

| Field | Required | Description |
|---|---|---|
| **Metric** | Yes | What to measure (see [Available Metrics](#available-metrics)) |
| **Aggregation** | Yes | How to combine values over the time window (see [Aggregations](#aggregations)) |
| **Operator** | Yes | The comparison operator (`>`, `<`, `>=`, `<=`, `=`, `!=`) |
| **Threshold** | Yes | The value to compare against |
| **Time Window** | Yes | How many minutes of data to look back (e.g., `60` = last 1 hour) |

**Example:** `Average of Latency > 3` over a `30 minute` window means: "If the average latency across all calls in the last 30 minutes exceeds 3 seconds, fire the alert."

#### Agent Selection

Choose which agents this alert applies to:

- **All Agents** — monitors every agent in your organization (default)
- **Specific Agents** — select one or more agents to scope the alert

#### Notification Settings

| Field | Required | Description |
|---|---|---|
| **Notification Frequency** | Yes | How often to re-notify if the condition persists (see [Notification Frequency](#notification-frequency)) |
| **Email Recipients** | No | One or more email addresses to receive alert emails |
| **Webhooks** | No | One or more webhook URLs (e.g., Slack incoming webhooks) |

You must configure at least one email or webhook for notifications to work.

### Step 3: Save

Click **Create Alert**. Your alert is now **Active** and will be evaluated automatically.

---

## Available Metrics

| Metric | Value | Description |
|---|---|---|
| **Number of Calls** | `number_of_calls` | Total count of calls in the time window |
| **Call Duration** | `call_duration` | Duration of calls (in seconds) |
| **Error Rate** | `error_rate` | Percentage of calls that resulted in errors |
| **Success Rate** | `success_rate` | Percentage of calls that completed successfully |
| **Latency** | `latency` | Response latency of the voice AI agent |
| **Custom** | `custom` | Custom metric (for advanced use cases) |

## Aggregations

Aggregations determine how metric values are combined over the time window:

| Aggregation | Value | Description |
|---|---|---|
| **Sum** | `sum` | Total sum of all values |
| **Average** | `avg` | Arithmetic mean of all values |
| **Count** | `count` | Number of data points |
| **Minimum** | `min` | Lowest value in the window |
| **Maximum** | `max` | Highest value in the window |

## Operators

| Operator | Description |
|---|---|
| `>` | Greater than |
| `<` | Less than |
| `>=` | Greater than or equal to |
| `<=` | Less than or equal to |
| `=` | Equal to |
| `!=` | Not equal to |

---

## Notification Channels

### Slack Webhooks

EfficientAI sends rich Slack messages using [Block Kit](https://api.slack.com/block-kit) formatting. Each notification includes:

- Alert name and severity
- The triggered metric value vs. the threshold
- Timestamp and agent scope

**To set up a Slack webhook:**

1. Go to your Slack workspace's **Apps** settings
2. Create or select an **Incoming Webhook** app
3. Choose the channel to post to
4. Copy the webhook URL (it looks like `https://hooks.slack.com/services/T.../B.../xxx`)
5. Paste it in the alert's **Webhook** field

### Email Notifications

Email alerts are sent as rich HTML emails containing:

- Alert name and description
- Triggered value, threshold, and operator
- Metric type, aggregation, and time window
- Agent scope information
- Timestamp

**Requirements:** Email notifications require SMTP to be configured in your EfficientAI deployment. See the [Configuration Reference](/docs/reference/configuration) for SMTP settings.

---

## Notification Frequency

The notification frequency controls how often you are re-notified when an alert condition remains true. This prevents notification fatigue.

| Frequency | Cooldown | Description |
|---|---|---|
| **Immediate** | None | Notify every time the alert evaluates as triggered |
| **Hourly** | 1 hour | At most one notification per hour |
| **Daily** | 24 hours | At most one notification per day |
| **Weekly** | 7 days | At most one notification per week |

If an alert fires and you were already notified within the cooldown period, the alert will still be evaluated (and recorded in history) but no new notification will be sent.

---

## Alert Lifecycle

### Statuses

| Status | Description |
|---|---|
| **Active** | The alert is being evaluated on every cycle (default) |
| **Paused** | The alert exists but is temporarily not being evaluated |
| **Disabled** | The alert is fully disabled |

You can **Pause** and **Resume** alerts at any time from the alert detail page.

### Alert History Statuses

Each alert history entry progresses through:

| Status | Description |
|---|---|
| **Triggered** | The alert condition was met |
| **Notified** | Notifications were sent successfully |
| **Acknowledged** | A team member has acknowledged the alert |
| **Resolved** | The issue has been resolved |

---

## Managing Alerts

### Viewing Alert Details

Click on any alert in the list to open its **Detail Page**. Here you'll see:

- **Metric Condition** — the full rule (aggregation, metric, operator, threshold, time window)
- **Agent Scope** — which agents are monitored
- **Notification Config** — email recipients and webhooks
- **Recent Alert History** — the last 10 triggered events
- **Metadata** — created/updated timestamps and total trigger count

### Editing an Alert

From the alert detail page, click the **Edit** button. This switches to an inline edit form where you can modify any field:

- Basic information (name, description)
- Metric condition (metric, aggregation, operator, threshold, time window)
- Agent selection
- Notification settings (frequency, emails, webhooks)

Click **Save Changes** to apply, or **Cancel** to discard.

### Pausing / Resuming

Click the **Pause** button on the detail page to temporarily stop an alert from being evaluated. Click **Resume** to reactivate it. Pausing does not delete any history.

### Deleting an Alert

Click **Delete** on the detail page. This permanently removes the alert and all its history. This action cannot be undone.

---

## Testing & Debugging

### Trigger (Manual Evaluation)

The **Trigger** button on the alert detail page manually evaluates the alert right now, regardless of the automatic schedule. This is useful to:

- Verify your alert condition is configured correctly
- Check if a threshold is currently being breached
- Debug why an alert isn't firing

If the condition is met, a real notification is sent and an alert history record is created (just like an automatic evaluation). Cooldown rules still apply.

### Test Notification

The **Test Notification** button sends a sample notification to all configured channels (emails and webhooks) without evaluating the alert condition. This is useful to:

- Verify that your Slack webhook URL is correct
- Verify that email delivery is working
- Preview what the notification looks like

Test notifications are clearly labeled with a `[TEST]` prefix and use placeholder values. They do **not** create alert history records and ignore cooldown rules.

### Evaluate All

From the alerts list page, the **Evaluate All** button triggers evaluation of every active alert in your organization at once. The results banner shows:

- How many alerts were evaluated
- How many triggered
- How many were within cooldown
- How many had errors

---

## Automatic Evaluation

Alerts are automatically evaluated every **60 seconds** by a background worker (Celery Beat). You do not need to manually trigger evaluations — they run continuously as long as your workers are running.

The evaluation cycle:
1. Fetches all **active** alerts for the organization
2. For each alert, computes the metric over the configured time window
3. Compares the computed value against the threshold
4. If the condition is met and the cooldown has elapsed, sends notifications
5. Records the result in alert history

---

## API Reference

All alert endpoints are under `/api/v1/alerts` and require authentication via API key.

### Alerts

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/alerts` | Create a new alert |
| `GET` | `/alerts` | List all alerts |
| `GET` | `/alerts/{alert_id}` | Get alert details |
| `PUT` | `/alerts/{alert_id}` | Update an alert |
| `DELETE` | `/alerts/{alert_id}` | Delete an alert |
| `POST` | `/alerts/{alert_id}/toggle` | Pause or resume an alert |
| `POST` | `/alerts/{alert_id}/trigger` | Manually evaluate an alert |
| `POST` | `/alerts/{alert_id}/test-notification` | Send a test notification |
| `POST` | `/alerts/evaluate/all` | Evaluate all active alerts |

### Alert History

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/alerts/history/all` | List all alert history |
| `GET` | `/alerts/{alert_id}/history` | List history for a specific alert |
| `GET` | `/alerts/history/{history_id}` | Get a specific history entry |
| `PATCH` | `/alerts/history/{history_id}` | Update history (acknowledge/resolve) |

### Create Alert — Request Body

```json
{
  "name": "High Error Rate",
  "description": "Fires when error rate exceeds 10%",
  "metric_type": "error_rate",
  "aggregation": "avg",
  "operator": ">",
  "threshold_value": 10,
  "time_window_minutes": 60,
  "agent_ids": ["uuid-1", "uuid-2"],
  "notify_frequency": "hourly",
  "notify_emails": ["ops@company.com"],
  "notify_webhooks": ["https://hooks.slack.com/services/..."]
}
```

### Alert Response

```json
{
  "id": "uuid",
  "organization_id": "uuid",
  "name": "High Error Rate",
  "description": "Fires when error rate exceeds 10%",
  "metric_type": "error_rate",
  "aggregation": "avg",
  "operator": ">",
  "threshold_value": 10.0,
  "time_window_minutes": 60,
  "agent_ids": ["uuid-1", "uuid-2"],
  "notify_frequency": "hourly",
  "notify_emails": ["ops@company.com"],
  "notify_webhooks": ["https://hooks.slack.com/services/..."],
  "status": "active",
  "created_at": "2026-02-15T10:00:00Z",
  "updated_at": "2026-02-15T10:00:00Z"
}
```

---

## Configuration

### SMTP Settings (for Email Notifications)

To enable email notifications, configure the following in your `config.yml` or environment variables:

```yaml
smtp:
  host: "smtp.gmail.com"
  port: 587
  username: "your-email@gmail.com"
  password: "your-app-password"
  from_email: "alerts@yourcompany.com"
  from_name: "EfficientAI Alerts"
  use_tls: true
```

Or via environment variables:

| Variable | Description | Default |
|---|---|---|
| `SMTP_HOST` | SMTP server hostname | — |
| `SMTP_PORT` | SMTP server port | `587` |
| `SMTP_USERNAME` | SMTP authentication username | — |
| `SMTP_PASSWORD` | SMTP authentication password | — |
| `SMTP_FROM_EMAIL` | Sender email address | — |
| `SMTP_FROM_NAME` | Sender display name | `EfficientAI Alerts` |
| `SMTP_USE_TLS` | Enable TLS encryption | `true` |

### Celery Workers

Alert evaluation runs as a Celery Beat periodic task. Ensure your Celery workers and Beat scheduler are running:

```bash
# Start Celery worker
celery -A app.workers.celery_app worker --loglevel=info

# Start Celery Beat scheduler
celery -A app.workers.celery_app beat --loglevel=info
```

---

## Common Patterns

### Monitor Error Rate Spikes

```
Metric: Error Rate | Aggregation: Average | Operator: > | Threshold: 5 | Window: 30 min
```

Alert when the average error rate exceeds 5% in the last 30 minutes.

### Detect Call Volume Drops

```
Metric: Number of Calls | Aggregation: Count | Operator: < | Threshold: 10 | Window: 60 min
```

Alert when fewer than 10 calls are received in the last hour (possible outage).

### Track High Latency

```
Metric: Latency | Aggregation: Max | Operator: > | Threshold: 5 | Window: 15 min
```

Alert when any single call has latency above 5 seconds in the last 15 minutes.

### Monitor Success Rate

```
Metric: Success Rate | Aggregation: Average | Operator: < | Threshold: 90 | Window: 60 min
```

Alert when the average success rate drops below 90% in the last hour.
