import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageSquare, Sparkles, Activity, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getEvaluatorResultPlaceholder } from '../../lib/evaluatorResultQuery'
import { prefetchCallRecordingAudio, prefetchEvaluatorRecordingAudio } from '../../lib/waveformAudioCache'
import CallWaveformPlayer from './CallWaveformPlayer'
import SyntheticCallTracePanel from './SyntheticCallTracePanel'

type DrawerTab = 'transcript' | 'analysis' | 'pipeline'

const TABS: Array<{ id: DrawerTab; label: string; icon: typeof MessageSquare }> = [
  { id: 'transcript', label: 'Transcript', icon: MessageSquare },
  { id: 'analysis', label: 'Analysis', icon: Sparkles },
  { id: 'pipeline', label: 'Pipeline', icon: Activity },
]

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function getSpeakerLabel(speaker: string, agentName?: string): string {
  if (speaker === 'Speaker 1' || speaker === 'user' || speaker === 'caller') return 'Caller'
  if (speaker === 'assistant' || speaker === 'Speaker 2' || speaker === 'bot') return agentName || 'Agent'
  return agentName || 'Agent'
}

function isUserSpeaker(speaker: string): boolean {
  return speaker === 'Speaker 1' || speaker === 'user' || speaker === 'caller'
}

export default function EvaluatorCallDetailPanel({
  evaluatorResultId,
  onClose,
}: {
  evaluatorResultId: string
  onClose?: () => void
}) {
  const [tab, setTab] = useState<DrawerTab>('transcript')
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!evaluatorResultId) return
    prefetchEvaluatorRecordingAudio(evaluatorResultId)
  }, [evaluatorResultId])

  const { data: result, isFetching, isError, error } = useQuery({
    queryKey: ['evaluator-result', evaluatorResultId],
    queryFn: () => apiClient.getEvaluatorResult(evaluatorResultId, true),
    enabled: Boolean(evaluatorResultId),
    placeholderData: () => getEvaluatorResultPlaceholder(queryClient, evaluatorResultId),
    staleTime: 30_000,
  })

  const detailsReady = Boolean(result?.speaker_segments || result?.transcription || result?.call_data)

  const callAnalysis = useMemo(() => {
    const fromCallData = (result?.call_data?.call_analysis || {}) as Record<string, unknown>
    const fromMetrics = result?.metric_scores || {}
    return {
      call_summary:
        (fromCallData.call_summary as string | undefined) ||
        (fromMetrics.summary?.value as string | undefined) ||
        null,
      user_sentiment:
        (fromCallData.user_sentiment as string | undefined) ||
        (fromMetrics.sentiment?.value as string | undefined) ||
        'Neutral',
      call_successful:
        fromCallData.call_successful !== undefined
          ? Boolean(fromCallData.call_successful)
          : fromMetrics.successful?.value !== undefined
            ? Boolean(fromMetrics.successful.value)
            : null,
    }
  }, [result])

  const callShortId =
    typeof result?.call_data?.call_short_id === 'string' ? result.call_data.call_short_id : undefined

  useEffect(() => {
    if (!callShortId) return
    prefetchCallRecordingAudio(callShortId, false)
  }, [callShortId])

  if (!result && !isFetching) {
    return <div className="p-8 text-sm text-gray-600">Call details not found.</div>
  }

  const fetchError =
    isError && error
      ? (error as { response?: { data?: { detail?: string } }; message?: string }).response?.data
          ?.detail ||
        (error as { message?: string }).message ||
        'Failed to load call details'
      : null

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-50">
      <div className="shrink-0 border-b border-gray-200 bg-white px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-mono text-xl font-bold tracking-tight text-primary-600">
              #{result?.result_id ?? evaluatorResultId}
            </h2>
            <p className="mt-1 text-sm text-gray-600">
              {result?.agent?.name ? `${result.agent.name} · ` : ''}
              Transcript, analysis, and pipeline trace
            </p>
          </div>
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
            >
              <X className="h-5 w-5" />
            </button>
          ) : null}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="space-y-4">
          {fetchError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              {fetchError}
            </div>
          ) : null}
          <CallWaveformPlayer
            evaluatorResultId={callShortId ? undefined : evaluatorResultId}
            callShortId={callShortId}
            callRecordingId={callShortId}
            callData={result?.call_data}
            platform={result?.provider_platform}
          />

          <div className="flex flex-wrap gap-1 border-b border-gray-200 bg-white px-1">
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                  tab === id
                    ? 'border-primary-500 text-primary-800'
                    : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </button>
            ))}
          </div>

          {!detailsReady && tab !== 'pipeline' ? (
            <div className="space-y-3">
              <div className="h-48 animate-pulse rounded-xl bg-gray-100" />
            </div>
          ) : null}

          {detailsReady && tab === 'transcript' ? (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="max-h-[min(60vh,520px)] space-y-3 overflow-y-auto pr-1">
                {result?.speaker_segments && result.speaker_segments.length > 0 ? (
                  result.speaker_segments.map(
                    (segment: { speaker: string; text: string; start: number }, idx: number) => (
                    <div
                      key={idx}
                      className={`flex ${isUserSpeaker(segment.speaker) ? 'justify-end' : 'justify-start'}`}
                    >
                      <div
                        className={`max-w-[85%] rounded-2xl px-4 py-2.5 ${
                          isUserSpeaker(segment.speaker)
                            ? 'bg-indigo-600 text-white rounded-br-sm'
                            : 'bg-gray-100 text-gray-800 rounded-bl-sm'
                        }`}
                      >
                        <div
                          className={`mb-0.5 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider ${
                            isUserSpeaker(segment.speaker) ? 'text-indigo-200' : 'text-gray-400'
                          }`}
                        >
                          <span>{getSpeakerLabel(segment.speaker, result.agent?.name)}</span>
                          <span className="tabular-nums">{formatTime(segment.start)}</span>
                        </div>
                        <p className="text-sm leading-relaxed">{segment.text}</p>
                      </div>
                    </div>
                  ),
                  )
                ) : result?.transcription ? (
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
                    {result.transcription}
                  </p>
                ) : (
                  <p className="py-8 text-center text-sm text-gray-500">No transcript available.</p>
                )}
              </div>
            </div>
          ) : null}

          {detailsReady && tab === 'analysis' ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              {callAnalysis.call_summary ? (
                <div className="mb-4 rounded-lg border border-indigo-100 bg-indigo-50 p-4">
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-indigo-900">
                    Summary
                  </p>
                  <p className="text-sm leading-relaxed text-indigo-800">{callAnalysis.call_summary}</p>
                </div>
              ) : null}
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-gray-50 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                    Sentiment
                  </p>
                  <p className="mt-1 text-sm font-medium text-gray-900">{callAnalysis.user_sentiment}</p>
                </div>
                <div className="rounded-lg bg-gray-50 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                    Success
                  </p>
                  <p className="mt-1 text-sm font-medium text-gray-900">
                    {callAnalysis.call_successful === true
                      ? 'Successful'
                      : callAnalysis.call_successful === false
                        ? 'Unsuccessful'
                        : 'N/A'}
                  </p>
                </div>
              </div>
              {!callAnalysis.call_summary &&
              callAnalysis.call_successful == null &&
              callAnalysis.user_sentiment === 'Neutral' ? (
                <p className="mt-4 text-center text-sm text-gray-500">No call analysis available.</p>
              ) : null}
            </div>
          ) : null}

          {tab === 'pipeline' ? (
            <SyntheticCallTracePanel evaluatorResultId={evaluatorResultId} embedded />
          ) : null}
        </div>
      </div>
    </div>
  )
}
