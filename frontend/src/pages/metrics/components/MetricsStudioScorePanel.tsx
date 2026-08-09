import { Link } from 'react-router-dom'
import MetricScoreGrid from './MetricScoreGrid'
import MetricsStudioTranscriptPanel from './MetricsStudioTranscriptPanel'

type StudioRunResult = {
  id: string
  source_kind: string
  source_ref: string
  display_label?: string | null
  source_metadata?: Record<string, unknown> | null
  status: string
  metric_scores?: Record<
    string,
    {
      value?: unknown
      type?: string
      metric_name?: string
      rationale?: string | null
      skipped?: unknown
    }
  >
  error_message?: string | null
}

type MetricsStudioScorePanelProps = {
  result: StudioRunResult | null | undefined
  transcriptSource: string
  metricNameById: Record<string, string>
  childMetricIds: Set<string>
  draftMetricIds: Set<string>
  onPromoteDraft: (metricId: string) => void
}

export default function MetricsStudioScorePanel({
  result,
  transcriptSource,
  metricNameById,
  childMetricIds,
  draftMetricIds,
  onPromoteDraft,
}: MetricsStudioScorePanelProps) {
  if (!result) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500">
        Select a source to inspect scores.
      </div>
    )
  }

  const metadata = result.source_metadata ?? {}
  const evaluationTranscript =
    typeof metadata.evaluation_transcript === 'string'
      ? metadata.evaluation_transcript
      : null
  const transcriptSourceUsed =
    typeof metadata.transcript_source_used === 'string'
      ? metadata.transcript_source_used
      : transcriptSource

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">Scores & details</h3>
        <p className="text-sm text-gray-600 mt-1">{result.display_label || result.source_ref}</p>
      </div>

      <div className="text-sm text-gray-600 space-y-1">
        {typeof metadata.persona_name === 'string' && metadata.persona_name && (
          <p>
            <span className="font-medium text-gray-800">Persona:</span> {metadata.persona_name}
          </p>
        )}
        {typeof metadata.scenario_name === 'string' && metadata.scenario_name && (
          <p>
            <span className="font-medium text-gray-800">Scenario:</span> {metadata.scenario_name}
          </p>
        )}
        {typeof metadata.call_import_id === 'string' && metadata.call_import_id && (
          <p>
            <Link
              to={`/call-imports/${metadata.call_import_id}`}
              className="text-primary-700 hover:text-primary-900"
            >
              View call import →
            </Link>
          </p>
        )}
        {result.source_kind === 'evaluator_result' && (
          <p>
            <Link
              to={`/results/${result.source_ref}`}
              className="text-primary-700 hover:text-primary-900"
            >
              View full simulation →
            </Link>
          </p>
        )}
        {result.source_kind === 'call_recording' && (
          <p>
            <Link
              to={`/playground/call-recordings/${result.source_ref}`}
              className="text-primary-700 hover:text-primary-900"
            >
              View recording →
            </Link>
          </p>
        )}
      </div>

      {result.error_message && (
        <p className="text-sm text-red-600 rounded-md bg-red-50 border border-red-100 px-3 py-2">
          {result.error_message}
        </p>
      )}

      {result.status === 'completed' && (
        <MetricsStudioTranscriptPanel
          transcript={evaluationTranscript}
          transcriptSource={transcriptSourceUsed}
        />
      )}

      <div className="max-h-[36rem] overflow-y-auto pr-1">
        <MetricScoreGrid
          metricScores={result.metric_scores ?? {}}
          metricNameById={metricNameById}
          childMetricIds={childMetricIds}
          draftMetricIds={draftMetricIds}
          onPromoteDraft={onPromoteDraft}
        />
      </div>
    </div>
  )
}
