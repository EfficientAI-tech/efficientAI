import { Copy, Check, Link2, Loader2 } from 'lucide-react'
import { useState } from 'react'
import IncidentTimeline from './IncidentTimeline'
import IncidentChannelActivity from './IncidentChannelActivity'
import { buildIncidentTimeline, hasLifecycleSyncActivity } from './incidentActivityUtils'
import { isOpenIncident } from './alertUiUtils'

export type IncidentDetailItem = {
  id: string
  alert_id: string
  triggered_at: string
  triggered_value: number
  threshold_value: number
  status: string
  notified_at?: string
  notification_details?: Record<string, unknown>
  acknowledged_at?: string
  acknowledged_by?: string
  resolved_at?: string
  resolved_by?: string
  resolution_notes?: string
  context_data?: Record<string, unknown>
  alert?: { name?: string; description?: string }
}

type Props = {
  item: IncidentDetailItem
  statusBadge: React.ReactNode
  actions?: React.ReactNode
  isRefreshing?: boolean
}

export default function IncidentDetailPanel({
  item,
  statusBadge,
  actions,
  isRefreshing = false,
}: Props) {
  const [copied, setCopied] = useState(false)
  const steps = buildIncidentTimeline(item)
  const syncActivity = hasLifecycleSyncActivity(item.notification_details)

  const copyId = async () => {
    await navigator.clipboard.writeText(item.id)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-5 relative">
      {isRefreshing && (
        <div
          className="flex items-center gap-2 text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2"
          role="status"
          aria-live="polite"
        >
          <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
          Refreshing incident details…
        </div>
      )}
      <div
        className={`space-y-5 transition-opacity ${isRefreshing ? 'opacity-60 pointer-events-none' : ''}`}
      >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">
            {item.alert?.name || 'Alert'}
          </h3>
          <div className="flex flex-wrap items-center gap-2 mt-1">
            {statusBadge}
            {isOpenIncident(item.status) && (
              <span className="text-xs font-medium text-amber-800 bg-amber-50 px-2 py-0.5 rounded-full">
                Open
              </span>
            )}
            {syncActivity && (
              <span className="text-xs text-gray-600 inline-flex items-center gap-1">
                <Link2 className="w-3 h-3" />
                Lifecycle sync recorded
              </span>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={copyId}
          className="text-xs text-gray-500 hover:text-gray-800 inline-flex items-center gap-1 border border-gray-200 rounded-lg px-2 py-1"
          title="Incident ID (used for PagerDuty dedup)"
        >
          {copied ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
          <span className="font-mono truncate max-w-[140px]">{item.id}</span>
        </button>
      </div>

      <div className="grid sm:grid-cols-3 gap-3 text-sm">
        <div className="rounded-lg border border-gray-200 px-3 py-2">
          <div className="text-xs text-gray-500">Value / threshold</div>
          <div className="font-mono font-medium mt-0.5">
            <span className="text-red-600">{item.triggered_value.toLocaleString()}</span>
            <span className="text-gray-400 mx-1">/</span>
            <span className="text-gray-600">{item.threshold_value.toLocaleString()}</span>
          </div>
        </div>
        <div className="rounded-lg border border-gray-200 px-3 py-2 sm:col-span-2">
          <div className="text-xs text-gray-500">Opened</div>
          <div className="font-medium mt-0.5">{new Date(item.triggered_at).toLocaleString()}</div>
        </div>
      </div>

      <section>
        <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-3">
          Timeline
        </h4>
        <IncidentTimeline steps={steps} />
      </section>

      <section>
        <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-3">
          Channel activity
        </h4>
        <IncidentChannelActivity notificationDetails={item.notification_details} />
      </section>

      {actions && (
        <div className="flex flex-wrap justify-end gap-2 pt-2 border-t border-gray-100">{actions}</div>
      )}
      </div>
    </div>
  )
}
