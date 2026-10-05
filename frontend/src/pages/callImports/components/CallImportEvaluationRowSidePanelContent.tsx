import type { CallImportEvaluationRow } from '../../../types/api'
import TranscriptView from './TranscriptView'
import MetricFlowChart, { flowFromSequence } from './MetricFlowChart'
import {
  ClassificationScoreDetail,
  type ClassificationScoreView,
} from '../classificationScoreDisplay'

export type CallImportEvaluationRowSidePanelTabId =
  | 'production'
  | 'diarised'
  | 'scores'
  | 'flow'
  | 'metadata'

function formatScoreValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toString() : value.toFixed(2)
  }
  return String(value)
}

function formatRecordingDate(value: string | null | undefined): string {
  if (!value) return '-'
  const [year, month, day] = value.split('-')
  return year && month && day ? `${day}/${month}/${year}` : value
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

export interface CallImportEvaluationRowSidePanelContentProps {
  row: CallImportEvaluationRow
  activeTab: CallImportEvaluationRowSidePanelTabId
  displayMetrics: { id: string; name: string; hasRationale: boolean }[]
  parentMetrics: {
    id: string
    name: string
    selection_mode: 'single_choice' | 'multi_label' | null
    children: { id: string; name: string }[]
  }[]
}

export function CallImportEvaluationRowSidePanelContent({
  row,
  activeTab,
  displayMetrics,
  parentMetrics,
}: CallImportEvaluationRowSidePanelContentProps) {
  const productionText = row.production_transcript ?? null
  const diarisedText = row.diarised_transcript ?? null

  if (activeTab === 'production') {
    return (
      <div className="max-h-[min(38rem,calc(100vh-12rem))] overflow-y-auto">
        {productionText ? (
          <TranscriptView transcript={productionText} compact embedded />
        ) : (
          <p className="text-xs text-gray-500 italic">No production transcript on the source row.</p>
        )}
      </div>
    )
  }

  if (activeTab === 'diarised') {
    return (
      <div className="space-y-2">
        {row.diarised_transcript_status ? (
          <p className="text-[11px] text-gray-500">
            Diarisation status: {row.diarised_transcript_status}
            {row.diarised_transcript_error ? (
              <span className="text-red-700"> — {row.diarised_transcript_error}</span>
            ) : null}
          </p>
        ) : null}
        <div className="max-h-[min(38rem,calc(100vh-12rem))] overflow-y-auto">
          {diarisedText ? (
            <TranscriptView transcript={diarisedText} compact embedded />
          ) : (
            <p className="text-xs text-gray-500 italic">No diarised transcript on the source row.</p>
          )}
        </div>
      </div>
    )
  }

  if (activeTab === 'scores') {
    if (displayMetrics.length === 0) {
      return <p className="text-xs text-gray-400 italic">No metric scores recorded.</p>
    }
    return (
      <div className="space-y-2 max-h-[min(28rem,calc(100vh-20rem))] overflow-y-auto">
        {displayMetrics.map((metric) => {
          const score = (row.metric_scores || {})[metric.id]
          const hasScore = score !== undefined && score !== null && score !== ''
          const scoreObj =
            hasScore && typeof score === 'object' ? (score as Record<string, unknown>) : null
          const scoreType =
            scoreObj && typeof scoreObj.type === 'string' ? scoreObj.type.toLowerCase() : undefined
          const isClassification = scoreType === 'classification'
          const value = scoreObj && 'value' in scoreObj ? scoreObj.value : score
          const rationale =
            scoreObj && typeof scoreObj.rationale === 'string'
              ? String(scoreObj.rationale)
              : undefined
          const errorText =
            scoreObj && scoreObj.error ? String(scoreObj.error) : undefined
          return (
            <div key={metric.id} className="border border-gray-200 rounded-md p-3">
              <div
                className={
                  isClassification ? 'space-y-2' : 'flex items-baseline justify-between gap-3'
                }
              >
                <p className="text-sm font-medium text-gray-700 truncate">{metric.name}</p>
                {isClassification && scoreObj ? (
                  <ClassificationScoreDetail score={scoreObj as ClassificationScoreView} />
                ) : (
                  <span
                    className={`text-sm font-semibold ${
                      hasScore ? 'text-gray-900' : 'text-gray-400'
                    }`}
                  >
                    {hasScore ? formatScoreValue(value) : '—'}
                  </span>
                )}
              </div>
              {rationale ? (
                <p className="mt-1.5 text-xs text-gray-600 whitespace-pre-wrap leading-snug">
                  {rationale}
                </p>
              ) : null}
              {errorText ? (
                <p className="mt-1.5 text-xs text-red-700 whitespace-pre-wrap leading-snug">
                  {errorText}
                </p>
              ) : null}
            </div>
          )
        })}
      </div>
    )
  }

  if (activeTab === 'flow') {
    const flowEntries = parentMetrics
      .map((parent) => {
        const score = (row.metric_scores || {})[parent.id]
        if (!score || typeof score !== 'object') return null
        const sequence = (score as { sequence?: unknown }).sequence
        if (!Array.isArray(sequence) || sequence.length === 0) return null
        const childByKey: Record<string, { id: string; name: string }> = {}
        for (const child of parent.children) {
          childByKey[child.id] = child
          childByKey[child.name] = child
          childByKey[child.name.toLowerCase().replace(/\s+/g, '_')] = child
        }
        const discovered = Array.isArray((score as { discovered_labels?: unknown }).discovered_labels)
          ? ((score as { discovered_labels: Array<{ key?: string; name?: string }> })
              .discovered_labels).filter(
              (d): d is { key: string; name?: string } =>
                typeof d?.key === 'string' && d.key.length > 0,
            )
          : []
        const data = flowFromSequence(
          parent.id,
          parent.name,
          sequence as string[],
          childByKey,
          parent.selection_mode,
          discovered,
        )
        if (data.nodes.length === 0) return null
        return { parent, data }
      })
      .filter(
        (
          entry,
        ): entry is {
          parent: (typeof parentMetrics)[number]
          data: ReturnType<typeof flowFromSequence>
        } => entry !== null,
      )

    if (flowEntries.length === 0) {
      return (
        <p className="text-xs text-gray-400 italic">
          No call-flow sequences for category metrics on this row.
        </p>
      )
    }

    return (
      <div className="space-y-3 max-h-[min(28rem,calc(100vh-20rem))] overflow-y-auto">
        {flowEntries.map(({ parent, data }) => (
          <div key={parent.id} className="border border-gray-200 rounded-md p-2">
            <p className="text-xs font-medium text-gray-700 mb-1.5">{parent.name}</p>
            <MetricFlowChart data={data} mode="per_call" height={220} />
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-3 max-h-[min(28rem,calc(100vh-20rem))] overflow-y-auto">
      <section className="border border-gray-200 rounded-md p-3 text-xs space-y-1.5">
        <p className="font-semibold text-gray-700 uppercase tracking-wider text-[10px]">
          Evaluation row
        </p>
        <div className="flex justify-between gap-2">
          <span className="text-gray-500">Status</span>
          <span className="text-gray-800">{row.status}</span>
        </div>
        {row.recording_date ? (
          <div className="flex justify-between gap-2">
            <span className="text-gray-500">Recorded</span>
            <span className="text-gray-800">{formatRecordingDate(row.recording_date)}</span>
          </div>
        ) : null}
        {row.finished_at ? (
          <div className="flex justify-between gap-2">
            <span className="text-gray-500">Finished</span>
            <span className="text-gray-800">{formatDateTime(row.finished_at)}</span>
          </div>
        ) : null}
        {row.recording_url ? (
          <div className="pt-1 border-t border-gray-100">
            <span className="text-gray-500 block mb-0.5">Source recording URL</span>
            <a
              href={row.recording_url}
              target="_blank"
              rel="noreferrer"
              className="text-primary-600 hover:text-primary-700 break-all underline"
            >
              {row.recording_url}
            </a>
          </div>
        ) : null}
      </section>

      {row.raw_columns && Object.keys(row.raw_columns).length > 0 ? (
        <section>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
            CSV Row ({Object.keys(row.raw_columns).length} columns)
          </h3>
          <dl className="border border-gray-200 rounded-md divide-y divide-gray-200 overflow-hidden">
            {Object.entries(row.raw_columns).map(([key, value]) => (
              <div key={key} className="grid grid-cols-[140px_1fr] text-xs">
                <dt className="bg-gray-50 px-3 py-1.5 font-medium text-gray-600 truncate border-r border-gray-200">
                  {key}
                </dt>
                <dd className="px-3 py-1.5 text-gray-800 break-words">
                  {value === null || value === undefined || value === ''
                    ? '—'
                    : String(value)}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}
    </div>
  )
}

export function evaluationRowHasCallFlow(
  row: CallImportEvaluationRow,
  parentMetrics: CallImportEvaluationRowSidePanelContentProps['parentMetrics'],
): boolean {
  return parentMetrics.some((parent) => {
    const score = (row.metric_scores || {})[parent.id]
    if (!score || typeof score !== 'object') return false
    const sequence = (score as { sequence?: unknown }).sequence
    return Array.isArray(sequence) && sequence.length > 0
  })
}
