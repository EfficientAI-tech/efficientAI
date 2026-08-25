import { Brain } from 'lucide-react'
import { Link } from 'react-router-dom'
import MetricScoreGrid from './MetricScoreGrid'
import MetricsStudioAudioPlayer from './MetricsStudioAudioPlayer'
import MetricsStudioTranscriptPanel from './MetricsStudioTranscriptPanel'
import { formatStudioModelLabel, type StudioRunModelInfo } from './MetricsStudioRunHeader'

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
  run: StudioRunModelInfo
  transcriptSource: string
  metricNameById: Record<string, string>
  childMetricIds: Set<string>
  draftMetricIds: Set<string>
  onPromoteDraft: (metricId: string) => void
}

export default function MetricsStudioScorePanel({
  result,
  run,
  transcriptSource,
  metricNameById,
  childMetricIds,
  draftMetricIds,
  onPromoteDraft,
}: MetricsStudioScorePanelProps) {
  if (!result) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-10 text-center text-sm text-gray-500">
        Select a source on the left to inspect scores and transcript.
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
    <div className="space-y-4">
      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-gray-900">Evaluation details</h3>
            <p className="text-sm text-gray-600 mt-1 truncate">
              {result.display_label || result.source_ref}
            </p>
          </div>
          <div className="inline-flex items-center gap-2 self-start rounded-lg border border-primary-100 bg-primary-50/60 px-3 py-2 text-xs text-primary-900">
            <Brain className="h-4 w-4 shrink-0 text-primary-600" />
            <div>
              <p className="font-medium">{formatStudioModelLabel(run)}</p>
              <p className="text-primary-700/80 mt-0.5">Evaluation model</p>
            </div>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-600">
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
            <Link
              to={`/call-imports/${metadata.call_import_id}`}
              className="text-primary-700 hover:text-primary-900"
            >
              View call import →
            </Link>
          )}
          {result.source_kind === 'evaluator_result' && (
            <Link
              to={`/results/${result.source_ref}`}
              className="text-primary-700 hover:text-primary-900"
            >
              View full simulation →
            </Link>
          )}
          {result.source_kind === 'call_recording' && (
            <Link
              to={`/playground/call-recordings/${result.source_ref}`}
              className="text-primary-700 hover:text-primary-900"
            >
              View recording →
            </Link>
          )}
        </div>

        {result.error_message && (
          <p className="mt-3 text-sm text-red-600 rounded-md bg-red-50 border border-red-100 px-3 py-2">
            {result.error_message}
          </p>
        )}
      </section>

      {result.status === 'completed' && (
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3">
            Analysis results
          </h4>
          <MetricScoreGrid
            metricScores={result.metric_scores ?? {}}
            metricNameById={metricNameById}
            childMetricIds={childMetricIds}
            draftMetricIds={draftMetricIds}
            onPromoteDraft={onPromoteDraft}
          />
        </section>
      )}

      <MetricsStudioAudioPlayer
        sourceKind={result.source_kind}
        sourceRef={result.source_ref}
        metadata={metadata}
      />

      {result.status === 'completed' && (
        <MetricsStudioTranscriptPanel
          transcript={evaluationTranscript}
          transcriptSource={transcriptSourceUsed}
        />
      )}
    </div>
  )
}
