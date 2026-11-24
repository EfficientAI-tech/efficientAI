import { AlertCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { CallRowSidePanel } from '../../callImports/components/CallRowSidePanel'
import MetricScoreGrid from './MetricScoreGrid'
import type { StudioRunResult } from './MetricsStudioScorePanel'
import type { StudioRunModelInfo } from './MetricsStudioRunHeader'
import { formatStudioModelLabel } from './MetricsStudioRunHeader'
import TranscriptView from '../../callImports/components/TranscriptView'
import { ResultStatusChip } from './MetricsStudioRunHeader'
import MetricsStudioAudioPlayer from './MetricsStudioAudioPlayer'

export type StudioResultPanelTab = 'transcript' | 'scores' | 'details'

function pickString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function transcriptSourceLabel(source: string): string {
  return source === 'production' ? 'Production (CSV)' : 'Diarised'
}

type MetricsStudioResultSidePanelProps = {
  result: StudioRunResult
  run: StudioRunModelInfo
  transcriptSource: string
  activeTab: StudioResultPanelTab
  onTabChange: (tab: StudioResultPanelTab) => void
  onClose: () => void
  metricNameById: Record<string, string>
  childMetricIds: Set<string>
  draftMetricIds: Set<string>
  onPromoteDraft: (metricId: string) => void
}

export default function MetricsStudioResultSidePanel({
  result,
  run,
  transcriptSource,
  activeTab,
  onTabChange,
  onClose,
  metricNameById,
  childMetricIds,
  draftMetricIds,
  onPromoteDraft,
}: MetricsStudioResultSidePanelProps) {
  const metadata = result.source_metadata ?? {}
  const evaluationTranscript =
    typeof metadata.evaluation_transcript === 'string' ? metadata.evaluation_transcript : null
  const transcriptSourceUsed =
    typeof metadata.transcript_source_used === 'string'
      ? metadata.transcript_source_used
      : transcriptSource
  const scoredHint =
    transcriptSourceUsed === 'production' ? 'Scored' : transcriptSourceUsed === 'diarised' ? 'Scored' : undefined

  const recordingS3Key =
    pickString(metadata.audio_s3_key) ?? pickString(metadata.recording_s3_key)

  const tabs = [
    {
      id: 'transcript',
      label: transcriptSourceLabel(transcriptSourceUsed),
      hint: scoredHint,
    },
    { id: 'scores', label: 'Scores' },
    { id: 'details', label: 'Details' },
  ]

  return (
    <CallRowSidePanel
      onClose={onClose}
      title={result.display_label || result.source_ref}
      headerMeta={
        <>
          <ResultStatusChip status={result.status} />
          <span className="text-xs text-gray-500">{formatStudioModelLabel(run)}</span>
        </>
      }
      errorBanner={
        result.error_message ? (
          <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-800 flex items-start gap-2">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{result.error_message}</span>
          </div>
        ) : undefined
      }
      recordingS3Key={recordingS3Key}
      tabs={tabs}
      activeTab={activeTab}
      onTabChange={(tabId) => onTabChange(tabId as StudioResultPanelTab)}
    >
      {activeTab === 'transcript' && (
        <div className="max-h-[min(42rem,calc(100vh-14rem))] overflow-y-auto">
          {evaluationTranscript?.trim() ? (
            <TranscriptView transcript={evaluationTranscript} compact embedded />
          ) : (
            <p className="text-sm text-gray-500 italic">
              {result.status === 'completed'
                ? 'No transcript stored for this source.'
                : 'Transcript will appear when scoring completes.'}
            </p>
          )}
        </div>
      )}

      {activeTab === 'scores' && (
        <div className="space-y-3">
          {result.status === 'completed' ? (
            <MetricScoreGrid
              metricScores={result.metric_scores ?? {}}
              metricNameById={metricNameById}
              childMetricIds={childMetricIds}
              draftMetricIds={draftMetricIds}
              onPromoteDraft={onPromoteDraft}
            />
          ) : (
            <p className="text-sm text-gray-500">Scores appear when this row completes.</p>
          )}
        </div>
      )}

      {activeTab === 'details' && (
        <div className="space-y-4 text-sm text-gray-600">
          {!recordingS3Key && (
            <MetricsStudioAudioPlayer
              sourceKind={result.source_kind}
              sourceRef={result.source_ref}
              metadata={metadata}
            />
          )}
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
          <p className="text-xs text-gray-500 font-mono break-all">{result.source_ref}</p>
          {typeof metadata.call_import_id === 'string' && metadata.call_import_id && (
            <Link
              to={`/call-imports/${metadata.call_import_id}`}
              className="text-primary-700 hover:text-primary-900 text-sm font-medium"
            >
              View call import →
            </Link>
          )}
          {result.source_kind === 'evaluator_result' && (
            <Link
              to={`/results/${result.source_ref}`}
              className="text-primary-700 hover:text-primary-900 text-sm font-medium"
            >
              View full simulation →
            </Link>
          )}
          {result.source_kind === 'call_recording' && (
            <Link
              to={`/playground/call-recordings/${result.source_ref}`}
              className="text-primary-700 hover:text-primary-900 text-sm font-medium"
            >
              View recording →
            </Link>
          )}
        </div>
      )}
    </CallRowSidePanel>
  )
}