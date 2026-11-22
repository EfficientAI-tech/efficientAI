import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Loader2, Pencil, RotateCcw, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorMessage } from '../../lib/apiErrors'
import type { CopilotAction } from '../../lib/copilotApi'
import { SchemaForm, type JsonSchema } from './SchemaForm'

const STATUS_STYLES: Record<string, string> = {
  proposed: 'bg-blue-50 text-blue-700',
  applying: 'bg-blue-50 text-blue-700',
  applied: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-red-50 text-red-700',
  rejected: 'bg-gray-100 text-gray-600',
  expired: 'bg-gray-100 text-gray-600',
  undoing: 'bg-amber-50 text-amber-700',
  undone: 'bg-gray-100 text-gray-600',
}

const STATUS_LABELS: Record<string, string> = {
  proposed: 'Needs your confirmation',
  applying: 'Applying…',
  applied: 'Done',
  failed: 'Failed',
  rejected: 'Rejected',
  expired: 'Expired',
  undoing: 'Undoing…',
  undone: 'Undone',
}

function formatEstimate(estimate: Record<string, unknown>): string[] {
  return Object.entries(estimate)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== 'object')
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${typeof v === 'number' ? v.toLocaleString() : String(v)}`)
}

/**
 * A change the assistant proposed. Nothing happens until the user confirms.
 * `action` is the latest server state (from the session's actions list) when
 * known, else the snapshot that streamed with the reply.
 */
export function ProposalCard({ action, onChanged }: { action: CopilotAction; onChanged: (a: CopilotAction) => void }) {
  const [editing, setEditing] = useState(false)
  const [payload, setPayload] = useState<Record<string, unknown>>(action.payload)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!editing) setPayload(action.payload)
  }, [action.payload, editing])

  const run = async (fn: () => Promise<CopilotAction>) => {
    setBusy(true)
    setError(null)
    try {
      onChanged(await fn())
      setEditing(false)
    } catch (err) {
      setError(getApiErrorMessage(err, 'That did not work. Try again.'))
    } finally {
      setBusy(false)
    }
  }

  const pending = action.status === 'proposed'
  const links = [...(action.result?.created ?? []), ...(action.result?.updated ?? [])]

  return (
    <div className="mt-2 rounded-lg border border-gray-200 bg-white text-sm">
      <div className="flex items-start justify-between gap-2 border-b border-gray-100 px-3 py-2">
        <div className="min-w-0">
          <div className="font-medium text-gray-900">{action.title}</div>
          <div className="text-xs text-gray-600">{action.summary}</div>
        </div>
        <span className={`flex-shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium ${STATUS_STYLES[action.status] ?? ''}`}>
          {STATUS_LABELS[action.status] ?? action.status}
        </span>
      </div>

      {action.cost_estimate && pending && (
        <div className="border-b border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {formatEstimate(action.cost_estimate).map((line) => (
            <div key={line}>{line}</div>
          ))}
        </div>
      )}

      {pending && editing && action.payload_schema && (
        <div className="max-h-80 overflow-y-auto px-3 py-2">
          <SchemaForm schema={action.payload_schema as JsonSchema} value={payload} onChange={setPayload} disabled={busy} />
        </div>
      )}

      {links.length > 0 && (
        <ul className="space-y-0.5 px-3 py-2 text-xs">
          {links.map((ref) => (
            <li key={`${ref.type}:${ref.id}`}>
              <span className="text-gray-500">{ref.type}: </span>
              {ref.link ? (
                <Link className="text-gray-900 underline" to={ref.link}>
                  {ref.name ?? ref.id}
                </Link>
              ) : (
                <span className="text-gray-900">{ref.name ?? ref.id}</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {(error || action.error) && (
        <div className="px-3 py-1.5 text-xs text-red-700">{error ?? action.error}</div>
      )}

      {pending && (
        <div className="flex items-center justify-end gap-2 border-t border-gray-100 px-3 py-2">
          {action.payload_schema && !editing && (
            <button
              type="button"
              className="mr-auto inline-flex items-center gap-1 text-xs text-gray-600 hover:text-gray-900"
              onClick={() => setEditing(true)}
            >
              <Pencil className="h-3.5 w-3.5" /> Edit
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            className="inline-flex items-center gap-1 rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            onClick={() => run(() => apiClient.copilot.rejectAction(action.id))}
          >
            <X className="h-3.5 w-3.5" /> Reject
          </button>
          <button
            type="button"
            disabled={busy}
            className="inline-flex items-center gap-1 rounded-md bg-gray-900 px-2 py-1 text-xs text-white hover:bg-gray-800 disabled:opacity-50"
            onClick={() => run(() => apiClient.copilot.confirmAction(action.id, editing ? payload : undefined))}
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            {action.costly ? 'Confirm and run' : 'Confirm'}
          </button>
        </div>
      )}

      {action.undoable && (
        <div className="flex justify-end border-t border-gray-100 px-3 py-2">
          <button
            type="button"
            disabled={busy}
            className="inline-flex items-center gap-1 text-xs text-gray-600 hover:text-gray-900 disabled:opacity-50"
            onClick={() => run(() => apiClient.copilot.undoAction(action.id))}
          >
            <RotateCcw className="h-3.5 w-3.5" /> Undo
          </button>
        </div>
      )}
    </div>
  )
}
