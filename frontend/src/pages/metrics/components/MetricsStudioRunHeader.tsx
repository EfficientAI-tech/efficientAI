import { format } from 'date-fns'
import { CheckCircle, Clock, Loader, RefreshCw, XCircle } from 'lucide-react'
import Button from '../../../components/Button'

type StudioRun = {
  id: string
  name?: string | null
  status: string
  total_items: number
  completed_items: number
  failed_items: number
  created_at: string
}

type MetricsStudioRunHeaderProps = {
  run: StudioRun
  onRetryFailed?: () => void
  retryPending?: boolean
}

function RunStatusChip({ status }: { status: string }) {
  const configs: Record<string, { label: string; className: string; icon: React.ReactNode }> = {
    pending: {
      label: 'Pending',
      className: 'bg-slate-100 text-slate-700',
      icon: <Clock className="h-3.5 w-3.5" />,
    },
    running: {
      label: 'Running',
      className: 'bg-amber-100 text-amber-800',
      icon: <Loader className="h-3.5 w-3.5 animate-spin" />,
    },
    partial: {
      label: 'Partial',
      className: 'bg-orange-100 text-orange-800',
      icon: <Clock className="h-3.5 w-3.5" />,
    },
    completed: {
      label: 'Completed',
      className: 'bg-emerald-100 text-emerald-800',
      icon: <CheckCircle className="h-3.5 w-3.5" />,
    },
    failed: {
      label: 'Failed',
      className: 'bg-rose-100 text-rose-800',
      icon: <XCircle className="h-3.5 w-3.5" />,
    },
  }
  const config = configs[status] ?? {
    label: status,
    className: 'bg-gray-100 text-gray-700',
    icon: null,
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium capitalize ${config.className}`}
    >
      {config.icon}
      {config.label}
    </span>
  )
}

export default function MetricsStudioRunHeader({
  run,
  onRetryFailed,
  retryPending,
}: MetricsStudioRunHeaderProps) {
  const progress =
    run.total_items > 0 ? Math.round((run.completed_items / run.total_items) * 100) : 0

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">
            {run.name || `Studio run ${run.id.slice(0, 8)}`}
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            {format(new Date(run.created_at), 'MMM d, yyyy HH:mm')}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <RunStatusChip status={run.status} />
          {run.failed_items > 0 && onRetryFailed && (
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<RefreshCw className="h-4 w-4" />}
              disabled={retryPending}
              onClick={onRetryFailed}
            >
              Retry failed
            </Button>
          )}
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between text-xs text-gray-600 mb-1.5">
          <span>
            {run.completed_items}/{run.total_items} completed
            {run.failed_items > 0 ? ` · ${run.failed_items} failed` : ''}
          </span>
          <span>{progress}%</span>
        </div>
        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-primary-600 rounded-full transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    </div>
  )
}

export function ResultStatusChip({ status }: { status: string }) {
  return <RunStatusChip status={status} />
}
