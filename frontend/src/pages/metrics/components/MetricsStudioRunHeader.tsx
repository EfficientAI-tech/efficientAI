import { format } from 'date-fns'
import {
  Brain,
  CheckCircle,
  Clock,
  FileText,
  Loader,
  RefreshCw,
  XCircle,
} from 'lucide-react'
import Button from '../../../components/Button'

export type StudioRunModelInfo = {
  llm_provider?: string | null
  llm_model?: string | null
}

type StudioRun = StudioRunModelInfo & {
  id: string
  name?: string | null
  status: string
  total_items: number
  completed_items: number
  failed_items: number
  created_at: string
  transcript_source?: string | null
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

function MetaPill({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <div className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs">
      <span className="text-gray-400">{icon}</span>
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-900">{value}</span>
    </div>
  )
}

export function formatStudioModelLabel(run: StudioRunModelInfo): string {
  const provider = run.llm_provider?.trim()
  const model = run.llm_model?.trim()
  if (provider && model) return `${provider} / ${model}`
  if (provider) return provider
  if (model) return model
  return 'Organization default'
}

function formatTranscriptSourceLabel(source?: string | null): string {
  return source === 'production' ? 'Production (CSV)' : 'Diarised'
}

export default function MetricsStudioRunHeader({
  run,
  onRetryFailed,
  retryPending,
}: MetricsStudioRunHeaderProps) {
  const progress =
    run.total_items > 0 ? Math.round((run.completed_items / run.total_items) * 100) : 0
  const showProgressBar = run.status === 'running' || run.status === 'pending'

  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-gray-900 truncate">
            {run.name || `Studio run ${run.id.slice(0, 8)}`}
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {format(new Date(run.created_at), 'MMM d, yyyy HH:mm')}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
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

      <div className="flex flex-wrap items-center gap-2">
        <MetaPill
          icon={<Brain className="h-3.5 w-3.5" />}
          label="Model"
          value={formatStudioModelLabel(run)}
        />
        <MetaPill
          icon={<FileText className="h-3.5 w-3.5" />}
          label="Transcript"
          value={formatTranscriptSourceLabel(run.transcript_source)}
        />
        <MetaPill
          icon={<CheckCircle className="h-3.5 w-3.5" />}
          label="Progress"
          value={`${run.completed_items}/${run.total_items}${
            run.failed_items > 0 ? ` (${run.failed_items} failed)` : ''
          }`}
        />
      </div>

      {showProgressBar && (
        <div className="flex items-center gap-3">
          <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-primary-600 rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="text-xs tabular-nums text-gray-500 shrink-0">{progress}%</span>
        </div>
      )}
    </div>
  )
}

export function ResultStatusChip({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: 'bg-slate-100 text-slate-600',
    running: 'bg-amber-100 text-amber-700',
    partial: 'bg-orange-100 text-orange-700',
    completed: 'bg-emerald-100 text-emerald-700',
    failed: 'bg-rose-100 text-rose-700',
  }

  return (
    <span
      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        styles[status] ?? 'bg-gray-100 text-gray-600'
      }`}
    >
      {status}
    </span>
  )
}
