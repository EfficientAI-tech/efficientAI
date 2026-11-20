import type { StudioRunResult } from './MetricsStudioScorePanel'
import { ResultStatusChip } from './MetricsStudioRunHeader'
import {
  compactStudioScoreLabel,
  studioMetricRationale,
  type StudioMetricScoreEntry,
} from './studioResultScoreDisplay'

export type StudioResultTableColumn = {
  columnKey: string
  metricId: string
  name: string
  isRationale?: boolean
}

type MetricsStudioResultsTableProps = {
  results: StudioRunResult[]
  columns: StudioResultTableColumn[]
  selectedResultId: string | null
  onSelectResult: (resultId: string | null) => void
}

function sourceKindLabel(sourceKind: string): string {
  switch (sourceKind) {
    case 'call_import_row':
      return 'Import'
    case 'call_recording':
      return 'Recording'
    case 'evaluator_result':
      return 'Simulation'
    default:
      return sourceKind
  }
}

export default function MetricsStudioResultsTable({
  results,
  columns,
  selectedResultId,
  onSelectResult,
}: MetricsStudioResultsTableProps) {
  if (results.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center text-sm text-gray-500">
        No source results yet. Rows appear as scoring completes.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto border border-gray-200 rounded-lg bg-white">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="sticky left-0 z-10 bg-gray-50 px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              #
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500 min-w-[12rem]">
              Source
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Status
            </th>
            {columns.map((col) =>
              col.isRationale ? (
                <th
                  key={col.columnKey}
                  className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase min-w-[14rem] max-w-xs"
                  title={`${col.name} — LLM rationale`}
                >
                  <span className="flex flex-col items-start leading-tight normal-case">
                    <span className="text-xs font-medium text-gray-700">
                      {col.name}{' '}
                      <span className="text-gray-400 font-normal">— LLM rationale</span>
                    </span>
                  </span>
                </th>
              ) : (
                <th
                  key={col.columnKey}
                  className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500 whitespace-nowrap"
                  title={col.name}
                >
                  <span className="line-clamp-2 normal-case text-xs font-medium text-gray-700">
                    {col.name}
                  </span>
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {results.map((result, index) => {
            const selected = selectedResultId === result.id
            return (
              <tr
                key={result.id}
                onClick={() => onSelectResult(selected ? null : result.id)}
                className={`cursor-pointer transition-colors hover:bg-primary-50/40 ${
                  selected ? 'bg-primary-50/70' : ''
                }`}
              >
                <td className="sticky left-0 z-10 bg-inherit px-3 py-2 text-sm text-gray-600 whitespace-nowrap align-top">
                  {index + 1}
                </td>
                <td className="px-3 py-2 text-sm text-gray-900 align-top">
                  <p className="font-medium line-clamp-2 leading-snug">
                    {result.display_label || result.source_ref}
                  </p>
                  <p className="text-[11px] text-gray-500 mt-0.5">
                    {sourceKindLabel(result.source_kind)}
                  </p>
                </td>
                <td className="px-3 py-2 whitespace-nowrap align-top">
                  <ResultStatusChip status={result.status} />
                </td>
                {columns.map((col) => {
                  const score = result.metric_scores?.[col.metricId] as
                    | StudioMetricScoreEntry
                    | undefined
                  if (col.isRationale) {
                    const rationale = studioMetricRationale(score)
                    return (
                      <td
                        key={col.columnKey}
                        className="px-3 py-2 text-sm text-gray-600 align-top max-w-xs"
                        title={rationale}
                      >
                        {rationale ? (
                          <span className="block whitespace-pre-wrap break-words leading-snug line-clamp-4">
                            {rationale}
                          </span>
                        ) : (
                          <span className="text-gray-300">-</span>
                        )}
                      </td>
                    )
                  }
                  const label = compactStudioScoreLabel(score)
                  return (
                    <td
                      key={col.columnKey}
                      className="px-3 py-2 text-sm text-gray-800 whitespace-nowrap align-top"
                      title={label}
                    >
                      <span className="font-medium">{label}</span>
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}