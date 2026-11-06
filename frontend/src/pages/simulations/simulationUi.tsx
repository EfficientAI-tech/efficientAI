import { CheckCircle2, CircleDashed, Loader2, XCircle, Ban } from 'lucide-react'
import type { SimulationRunStatus } from '../../types/api'
import { isRunActive } from './simulationFormat'

const STATUS_STYLES: Record<SimulationRunStatus, { label: string; className: string }> = {
  queued: { label: 'Queued', className: 'bg-gray-100 text-gray-700' },
  preparing: { label: 'Preparing', className: 'bg-primary-50 text-primary-800' },
  running: { label: 'Running', className: 'bg-primary-100 text-primary-800' },
  ingesting: { label: 'Scoring', className: 'bg-primary-100 text-primary-800' },
  completed: { label: 'Completed', className: 'bg-green-50 text-green-700' },
  failed: { label: 'Failed', className: 'bg-red-50 text-red-700' },
  cancelled: { label: 'Cancelled', className: 'bg-gray-100 text-gray-600' },
}

export function RunStatusChip({ status }: { status: SimulationRunStatus }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.queued
  const Icon =
    status === 'completed'
      ? CheckCircle2
      : status === 'failed'
        ? XCircle
        : status === 'cancelled'
          ? Ban
          : status === 'queued'
            ? CircleDashed
            : Loader2
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${style.className}`}>
      <Icon className={`h-3.5 w-3.5 ${isRunActive(status) && status !== 'queued' ? 'animate-spin' : ''}`} />
      {style.label}
    </span>
  )
}

/** Pass/fail always ships icon + label, never color alone. */
export function PassBadge({ passed, status }: { passed?: boolean | null; status: string }) {
  if (status === 'failed') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-red-700">
        <XCircle className="h-3.5 w-3.5" /> Error
      </span>
    )
  }
  if (passed === null || passed === undefined) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-gray-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> In progress
      </span>
    )
  }
  return passed ? (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-green-700">
      <CheckCircle2 className="h-3.5 w-3.5" /> Pass
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-red-700">
      <XCircle className="h-3.5 w-3.5" /> Fail
    </span>
  )
}
