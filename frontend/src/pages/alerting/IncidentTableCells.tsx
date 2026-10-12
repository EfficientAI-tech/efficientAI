import { AlertTriangle, Bell, CheckCircle, Eye, XCircle } from 'lucide-react'
import { collectChannelAttempts } from './incidentActivityUtils'

export function IncidentStatusBadge({ status }: { status: string; compact?: boolean }) {
  const pad = 'px-2 py-0.5 text-xs'
  switch (status) {
    case 'triggered':
      return (
        <span
          className={`inline-flex items-center gap-1 font-medium bg-red-50 text-red-800 rounded-full ${pad}`}
        >
          <AlertTriangle className="w-3 h-3 shrink-0" />
          Triggered
        </span>
      )
    case 'notified':
      return (
        <span
          className={`inline-flex items-center gap-1 font-medium bg-amber-50 text-amber-900 rounded-full ${pad}`}
        >
          <Bell className="w-3 h-3 shrink-0" />
          Notified
        </span>
      )
    case 'acknowledged':
      return (
        <span
          className={`inline-flex items-center gap-1 font-medium bg-sky-50 text-sky-900 rounded-full ${pad}`}
        >
          <Eye className="w-3 h-3 shrink-0" />
          Acknowledged
        </span>
      )
    case 'resolved':
      return (
        <span
          className={`inline-flex items-center gap-1 font-medium bg-emerald-50 text-emerald-900 rounded-full ${pad}`}
        >
          <CheckCircle className="w-3 h-3 shrink-0" />
          Resolved
        </span>
      )
    default:
      return (
        <span className={`inline-flex font-medium bg-gray-100 text-gray-700 rounded-full ${pad}`}>
          {status}
        </span>
      )
  }
}

export function DeliverySummaryBadge({
  notificationDetails,
}: {
  notificationDetails?: Record<string, unknown> | null
}) {
  const attempts = collectChannelAttempts(notificationDetails)
  if (attempts.length === 0) return null

  const failed = attempts.filter(a => !a.success).length
  const ok = attempts.length - failed
  const synced = attempts.filter(a => a.phase !== 'initial').length

  if (failed > 0) {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs text-red-700"
        title={`${failed} channel delivery failed`}
      >
        <XCircle className="w-3 h-3 shrink-0" />
        {ok}/{attempts.length} delivered
      </span>
    )
  }

  return (
    <span
      className="inline-flex items-center gap-1 text-xs text-gray-600"
      title={synced > 0 ? `${synced} lifecycle sync deliveries` : 'All initial notifications delivered'}
    >
      <span className="text-gray-400">·</span>
      {ok}/{attempts.length} delivered
      {synced > 0 && <span className="text-gray-400">· sync</span>}
    </span>
  )
}
