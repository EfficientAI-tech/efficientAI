import { ALL_METRIC_TYPES } from './alertFormConstants'

export const OPEN_INCIDENT_STATUSES = new Set(['triggered', 'notified', 'acknowledged'])

export function isOpenIncident(status: string): boolean {
  return OPEN_INCIDENT_STATUSES.has(status)
}

export function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatAlertCondition(alert: {
  metric_type: string
  aggregation: string
  operator: string
  threshold_value: number
}): string {
  const metric =
    ALL_METRIC_TYPES.find(m => m.value === alert.metric_type)?.label || alert.metric_type
  const agg = alert.aggregation.toUpperCase()
  return `${agg} ${metric} ${alert.operator} ${alert.threshold_value}`
}

export function getNotificationFailures(
  notificationDetails?: Record<string, unknown> | null
): { channel?: string; error?: string }[] {
  const results = (notificationDetails as { results?: { success?: boolean; channel?: string; error?: string }[] })
    ?.results
  if (!Array.isArray(results)) return []
  return results.filter(r => !r.success)
}

export function countNotificationChannels(alert: {
  notify_emails?: string[] | null
  notify_webhooks?: string[] | null
  notify_pagerduty_routing_keys?: string[] | null
}): { email: number; slack: number; pagerduty: number; total: number } {
  const email = (alert.notify_emails || []).filter(e => e?.trim()).length
  const slack = (alert.notify_webhooks || []).filter(w => w?.trim()).length
  const pagerduty = (alert.notify_pagerduty_routing_keys || []).filter(k => k?.trim()).length
  return { email, slack, pagerduty, total: email + slack + pagerduty }
}
