import { AlertTriangle, FlaskConical, MessageSquare, ShieldAlert } from 'lucide-react'
import type { IssueSeverity, SessionKind, SessionStatus } from '../../../lib/sandbox'
import { SEVERITY_LABELS, STATUS_LABELS, sessionKindLabel } from '../../../lib/sandbox'

export function SessionTypeBadge({ kind }: { kind: SessionKind }) {
  const isSim = kind === 'simulation'
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
        isSim ? 'bg-indigo-50 text-indigo-800' : 'bg-sky-50 text-sky-800'
      }`}
    >
      {isSim ? <FlaskConical className="h-3 w-3" aria-hidden /> : <MessageSquare className="h-3 w-3" aria-hidden />}
      {sessionKindLabel(kind)}
    </span>
  )
}

export function SandboxStatusBadge({ status }: { status: SessionStatus }) {
  const tone =
    status === 'failed'
      ? 'bg-rose-50 text-rose-800'
      : status === 'completed' || status === 'ended'
        ? 'bg-emerald-50 text-emerald-800'
        : status === 'running' || status === 'active' || status === 'evaluating' || status === 'queued'
          ? 'bg-amber-50 text-amber-800'
          : 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      {STATUS_LABELS[status]}
    </span>
  )
}

export function IssueBadge({
  severity,
  label,
  onClick,
}: {
  severity: IssueSeverity
  label?: string
  onClick?: () => void
}) {
  const tone =
    severity === 'error'
      ? 'bg-rose-50 text-rose-800 border-rose-200'
      : severity === 'warning'
        ? 'bg-amber-50 text-amber-800 border-amber-200'
        : 'bg-slate-50 text-slate-700 border-slate-200'
  const Icon = severity === 'error' ? ShieldAlert : AlertTriangle
  const content = (
    <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${tone}`}>
      <Icon className="h-3 w-3" aria-hidden />
      <span>{label || SEVERITY_LABELS[severity]}</span>
    </span>
  )
  if (!onClick) return content
  return (
    <button type="button" onClick={onClick} className="rounded-md focus:outline-none focus:ring-2 focus:ring-amber-400">
      {content}
    </button>
  )
}

export function IssueCountChips({
  error,
  warning,
  onClick,
}: {
  error: number
  warning: number
  onClick?: () => void
}) {
  if (error === 0 && warning === 0) {
    return <span className="text-xs text-gray-400">None</span>
  }
  const body = (
    <span className="inline-flex items-center gap-1">
      {error > 0 && (
        <span className="inline-flex min-w-[1.25rem] justify-center rounded-full bg-rose-600 px-1.5 text-[11px] font-semibold text-white">
          {error}
          <span className="sr-only"> errors</span>
        </span>
      )}
      {warning > 0 && (
        <span className="inline-flex min-w-[1.25rem] justify-center rounded-full bg-amber-500 px-1.5 text-[11px] font-semibold text-white">
          {warning}
          <span className="sr-only"> warnings</span>
        </span>
      )}
    </span>
  )
  if (!onClick) return body
  return (
    <button type="button" onClick={onClick} className="rounded focus:outline-none focus:ring-2 focus:ring-amber-400">
      {body}
    </button>
  )
}

export function HealthBadge({
  count,
  severity,
  label,
  onClick,
}: {
  count: number
  severity: IssueSeverity
  label: string
  onClick?: () => void
}) {
  return (
    <IssueBadge
      severity={severity}
      label={label || `${count} failed call${count === 1 ? '' : 's'} in last run`}
      onClick={onClick}
    />
  )
}

export function RoleBadge({ role }: { role: 'A' | 'B' | 'human' }) {
  if (role === 'human') {
    return (
      <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-700">
        You
      </span>
    )
  }
  const isMain = role === 'A'
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${
        isMain ? 'bg-violet-50 text-violet-800' : 'bg-teal-50 text-teal-800'
      }`}
    >
      {isMain ? 'Main agent' : 'Test agent'}
    </span>
  )
}
