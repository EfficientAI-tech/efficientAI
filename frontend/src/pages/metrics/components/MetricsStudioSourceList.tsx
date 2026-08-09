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
      <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500">
        No source results yet.
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-200">
        <h3 className="text-sm font-semibold text-gray-900">Sources ({results.length})</h3>
      </div>
      <div className="divide-y divide-gray-100 max-h-[32rem] overflow-y-auto">
        {results.map((result) => {
          const Icon = sourceIcon(result.source_kind)
          const selected = (selectedResultId ?? results[0]?.id) === result.id
          const scoreCount = Object.keys(result.metric_scores ?? {}).length

          return (
            <button
              key={result.id}
              type="button"
              onClick={() => onSelect(result.id)}
              className={`w-full text-left px-4 py-3 transition-colors hover:bg-gray-50 ${
                selected ? 'bg-primary-50/60 border-l-2 border-l-primary-600' : 'border-l-2 border-l-transparent'
              }`}
            >
              <div className="flex items-start gap-3">
                <div
                  className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                    selected ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600'
                  }`}
                >
                  <Icon className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {result.display_label || result.source_ref}
                    </p>
                    <ResultStatusChip status={result.status} />
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {sourceKindLabel(result.source_kind)}
                    {scoreCount > 0 ? ` · ${scoreCount} metrics` : ''}
                  </p>
                  {result.source_ref !== result.display_label && (
                    <p className="text-xs text-gray-400 mt-0.5 truncate">{result.source_ref}</p>
                  )}
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
