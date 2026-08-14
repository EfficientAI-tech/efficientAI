import { Bot, Mic, Upload } from 'lucide-react'
import { ResultStatusChip } from './MetricsStudioRunHeader'

export type StudioRunResult = {
  id: string
  source_kind: string
  source_ref: string
  display_label?: string | null
  status: string
  metric_scores?: Record<string, unknown>
}

type MetricsStudioSourceListProps = {
  results: StudioRunResult[]
  selectedResultId: string | null
  onSelect: (resultId: string) => void
}

function sourceIcon(sourceKind: string) {
  switch (sourceKind) {
    case 'call_import_row':
      return Upload
    case 'call_recording':
      return Mic
    case 'evaluator_result':
      return Bot
    default:
      return Upload
  }
}

function sourceKindLabel(sourceKind: string): string {
  switch (sourceKind) {
    case 'call_import_row':
      return 'Call import'
    case 'call_recording':
      return 'Recording'
    case 'evaluator_result':
      return 'Simulation'
    default:
      return sourceKind
  }
}

export default function MetricsStudioSourceList({
  results,
  selectedResultId,
  onSelect,
}: MetricsStudioSourceListProps) {
  if (results.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
        No source results yet.
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden lg:sticky lg:top-4">
      <div className="px-3 py-2.5 border-b border-gray-200 bg-gray-50/80">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Sources · {results.length}
        </h3>
      </div>
      <div className="divide-y divide-gray-100 max-h-[calc(100vh-16rem)] overflow-y-auto">
        {results.map((result) => {
          const Icon = sourceIcon(result.source_kind)
          const selected = (selectedResultId ?? results[0]?.id) === result.id
          const scoreCount = Object.keys(result.metric_scores ?? {}).length

          return (
            <button
              key={result.id}
              type="button"
              onClick={() => onSelect(result.id)}
              className={`w-full text-left px-3 py-2.5 transition-colors hover:bg-gray-50 ${
                selected
                  ? 'bg-primary-50/70 border-l-2 border-l-primary-600'
                  : 'border-l-2 border-l-transparent'
              }`}
            >
              <div className="flex items-start gap-2.5">
                <div
                  className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${
                    selected ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600'
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-gray-900 line-clamp-2 leading-snug">
                      {result.display_label || result.source_ref}
                    </p>
                    <ResultStatusChip status={result.status} />
                  </div>
                  <p className="text-[11px] text-gray-500 mt-0.5">
                    {sourceKindLabel(result.source_kind)}
                    {scoreCount > 0 ? ` · ${scoreCount} metrics` : ''}
                  </p>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
