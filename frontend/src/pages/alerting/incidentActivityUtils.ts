export type ChannelAttempt = {
  phase: 'initial' | 'acknowledge' | 'recovery'
  channel: string
  label: string
  success: boolean
  error?: string
}

export type TimelineStep = {
  key: string
  tone: 'red' | 'amber' | 'blue' | 'emerald' | 'gray'
  title: string
  at?: string
  meta?: string
  body?: string
}

const CHANNEL_LABELS: Record<string, string> = {
  slack_webhook: 'Slack',
  email: 'Email',
  pagerduty: 'PagerDuty',
  pagerduty_acknowledge: 'PagerDuty (ack)',
  pagerduty_resolve: 'PagerDuty (resolve)',
  slack_acknowledge: 'Slack (ack)',
  slack_recovery: 'Slack (recovery)',
}

function normalizeAttempts(
  list: unknown,
  phase: ChannelAttempt['phase']
): ChannelAttempt[] {
  if (!Array.isArray(list)) return []
  return list.map((r: { channel?: string; success?: boolean; error?: string }) => ({
    phase,
    channel: r.channel || 'unknown',
    label: CHANNEL_LABELS[r.channel || ''] || r.channel || 'Channel',
    success: Boolean(r.success),
    error: r.error,
  }))
}

export function collectChannelAttempts(
  notificationDetails?: Record<string, unknown> | null
): ChannelAttempt[] {
  if (!notificationDetails) return []
  const d = notificationDetails as {
    results?: unknown
    lifecycle?: { acknowledge?: unknown; recovery?: unknown }
  }
  return [
    ...normalizeAttempts(d.results, 'initial'),
    ...normalizeAttempts(d.lifecycle?.acknowledge, 'acknowledge'),
    ...normalizeAttempts(d.lifecycle?.recovery, 'recovery'),
  ]
}

export function hasLifecycleSyncActivity(notificationDetails?: Record<string, unknown> | null): boolean {
  const d = notificationDetails as { lifecycle?: { acknowledge?: unknown; recovery?: unknown } }
  const ack = Array.isArray(d?.lifecycle?.acknowledge) && d.lifecycle.acknowledge.length > 0
  const rec = Array.isArray(d?.lifecycle?.recovery) && d.lifecycle.recovery.length > 0
  return ack || rec
}

function normalizeStatus(status: unknown): string {
  if (typeof status === 'string') return status.toLowerCase()
  if (status && typeof status === 'object' && 'value' in status) {
    return String((status as { value: string }).value).toLowerCase()
  }
  return String(status ?? '').toLowerCase()
}

export function buildIncidentTimeline(item: {
  triggered_at: string
  notified_at?: string
  acknowledged_at?: string
  resolved_at?: string
  acknowledged_by?: string
  resolved_by?: string
  resolution_notes?: string
  status: string
  context_data?: Record<string, unknown> | null
  notification_details?: Record<string, unknown> | null
}): TimelineStep[] {
  const steps: TimelineStep[] = []
  const ctx = item.context_data || {}
  const status = normalizeStatus(item.status)

  steps.push({
    key: 'triggered',
    tone: 'red',
    title: 'Incident opened',
    at: item.triggered_at,
    meta: 'Rule threshold exceeded',
  })

  if (item.notified_at) {
    steps.push({
      key: 'notified',
      tone: 'amber',
      title: 'Team notified',
      at: item.notified_at,
      meta: 'Initial alert sent to configured channels',
    })
  } else if (status === 'triggered') {
    const initial = collectChannelAttempts(item.notification_details).filter(
      a => a.phase === 'initial'
    )
    const anyFail = initial.some(a => !a.success)
    steps.push({
      key: 'notified-pending',
      tone: 'gray',
      title: anyFail ? 'Notification failed' : 'Notification pending',
      meta: 'Check channel activity below',
    })
  }

  if (typeof ctx.last_evaluated_at === 'string' && !item.resolved_at) {
    steps.push({
      key: 'eval',
      tone: 'gray',
      title: 'Last evaluation while open',
      at: ctx.last_evaluated_at,
      meta:
        typeof ctx.ok_evaluation_streak === 'number'
          ? `OK streak ${ctx.ok_evaluation_streak} (needs 2 to auto-close)`
          : 'Metric re-checked on schedule',
    })
  }

  if (item.acknowledged_at) {
    steps.push({
      key: 'ack',
      tone: 'blue',
      title: 'Acknowledged',
      at: item.acknowledged_at,
      meta: item.acknowledged_by ? `By ${item.acknowledged_by}` : undefined,
    })
  }

  if (item.resolved_at) {
    const auto = ctx.auto_resolved === true || item.resolved_by === 'system'
    steps.push({
      key: 'resolved',
      tone: 'emerald',
      title: auto ? 'Auto-resolved' : 'Resolved',
      at: item.resolved_at,
      meta: item.resolved_by ? `By ${item.resolved_by}` : undefined,
      body: item.resolution_notes || undefined,
    })
  } else if (
    isOpenStatus(status) &&
    typeof ctx.ok_evaluation_streak === 'number' &&
    ctx.ok_evaluation_streak > 0
  ) {
    steps.push({
      key: 'recovering',
      tone: 'gray',
      title: 'Recovering',
      meta: `Metric OK ${ctx.ok_evaluation_streak}/2 checks — incident stays open until auto-resolve`,
    })
  }

  return steps
}

function isOpenStatus(status: string): boolean {
  return status === 'triggered' || status === 'notified' || status === 'acknowledged'
}

export const PHASE_LABELS: Record<ChannelAttempt['phase'], string> = {
  initial: 'When fired',
  acknowledge: 'Acknowledge sync',
  recovery: 'Resolve / recovery sync',
}
