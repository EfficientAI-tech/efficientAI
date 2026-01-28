---
id: cron-jobs
title: Scheduled Tests (Cron Jobs)
sidebar_position: 3
---

# Scheduled Tests (Cron Jobs)

## What are Cron Jobs?

**Cron Jobs** let you schedule automated test calls to run on a recurring basis.

Instead of manually triggering evaluations, you can set up a schedule like "Run this test every day at 9 AM" and EfficientAI will automatically execute it.

---

## Use Cases

- **Daily Health Checks**: Run a test every morning to ensure your AI is working
- **Regression Testing**: Automatically test after deployments
- **Performance Monitoring**: Continuous testing throughout the day
- **Off-Hours Testing**: Run tests when traffic is low

---

## Creating a Cron Job

A cron job requires:

1. **Name**: A descriptive name for the schedule
2. **Cron Expression**: When to run (standard cron format)
3. **Timezone**: Which timezone to use
4. **Evaluators**: Which tests to run
5. **Max Runs** (optional): Limit total executions

---

## Cron Expression Format

Standard 5-field cron format:

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6, Sun=0)
│ │ │ │ │
* * * * *
```

### Examples

| Expression | Description |
|------------|-------------|
| `0 9 * * *` | Every day at 9:00 AM |
| `0 */2 * * *` | Every 2 hours |
| `30 8 * * 1-5` | 8:30 AM on weekdays |
| `0 0 1 * *` | First day of each month at midnight |
| `*/15 * * * *` | Every 15 minutes |

---

## Timezone Support

All standard timezones are supported (pytz format):

- `America/New_York`
- `Europe/London`
- `Asia/Kolkata`
- `UTC`

The cron expression is evaluated in your selected timezone.

---

## Status

| Status | Description |
|--------|-------------|
| **Active** | Job is scheduled and will run |
| **Paused** | Job is temporarily stopped |
| **Completed** | Job hit max runs and stopped |

---

## Example Setup

**"Daily Morning Test"**

```
Name: Daily Morning Test
Cron: 0 9 * * *
Timezone: America/New_York
Evaluators: [Support Bot Test, Sales Bot Test]
Max Runs: (empty = unlimited)
```

This runs the selected evaluators every day at 9 AM Eastern time.

---

## Managing Cron Jobs

From the Cron Jobs dashboard you can:
- **Create** new scheduled tests
- **Pause/Resume** existing jobs
- **Edit** schedule or evaluators
- **Delete** jobs you no longer need
- **View** next scheduled run time
