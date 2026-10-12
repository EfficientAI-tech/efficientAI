import { PHASE_LABELS, collectChannelAttempts } from './incidentActivityUtils'

type Props = {
  notificationDetails?: Record<string, unknown> | null
  compact?: boolean
}

function StatusPill({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-flex text-xs font-medium px-2 py-0.5 rounded-full ${
        ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'
      }`}
    >
      {ok ? 'Delivered' : 'Failed'}
    </span>
  )
}

export default function IncidentChannelActivity({ notificationDetails, compact }: Props) {
  const attempts = collectChannelAttempts(notificationDetails)

  if (attempts.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        No channel delivery recorded yet. Fired alerts show here after notifications run.
      </p>
    )
  }

  const phases = ['initial', 'acknowledge', 'recovery'] as const

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500">
        {compact
          ? 'Delivery per channel and sync phase.'
          : 'What was sent to Slack, email, and PagerDuty — including lifecycle sync when your org has it enabled.'}
      </p>
      {phases.map(phase => {
        const rows = attempts.filter(a => a.phase === phase)
        if (rows.length === 0) return null
        return (
          <div key={phase}>
            <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
              {PHASE_LABELS[phase]}
            </div>
            <ul className="rounded-lg border border-gray-200 divide-y divide-gray-100 overflow-hidden">
              {rows.map((row, i) => (
                <li
                  key={`${phase}-${row.channel}-${i}`}
                  className="flex items-start justify-between gap-3 px-3 py-2.5 bg-white text-sm"
                >
                  <div className="min-w-0">
                    <div className="font-medium text-gray-900">{row.label}</div>
                    {!row.success && (
                      <div className="text-xs text-red-600 mt-0.5 break-words">
                        {row.error || 'Delivery failed'}
                      </div>
                    )}
                  </div>
                  <StatusPill ok={row.success} />
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

export { DeliverySummaryBadge as ChannelActivitySummary } from './IncidentTableCells'
