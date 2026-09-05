import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageSquare, Sparkles, Activity, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { formatMessageTiming } from '../../lib/callTranscriptTiming'
import { transcriptBubbleClass, transcriptMetaClass } from './transcriptBubbleStyles'
import { isPlaygroundCallRecordingSource, isVoiceAiProviderPlatform } from '../../lib/callDetailRouting'
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

function segmentTimingLabel(segment: { start: number; end?: number }): string | null {
  return formatMessageTiming(segment.start, segment.end)
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
  const playgroundCallShortId =
    callShortId &&
    isPlaygroundCallRecordingSource(result?.call_recording_source) &&
    isVoiceAiProviderPlatform(result?.provider_platform)
      ? callShortId
      : undefined

  useEffect(() => {
    if (!playgroundCallShortId) return
    prefetchCallRecordingAudio(playgroundCallShortId, false)
  }, [playgroundCallShortId])

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

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="shrink-0 space-y-2.5 border-b border-gray-200 bg-gray-50 px-5 pb-3 pt-4">
          {fetchError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              {fetchError}
            </div>
          ) : null}
          <CallWaveformPlayer
            evaluatorResultId={playgroundCallShortId ? undefined : evaluatorResultId}
            callShortId={playgroundCallShortId}
            callData={result?.call_data}
            platform={result?.provider_platform}
          />

          <div className="flex flex-nowrap gap-0.5 overflow-x-auto border-b border-gray-200 bg-white px-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`inline-flex shrink-0 items-center gap-1.5 border-b-2 px-2.5 py-1.5 text-sm font-medium transition-colors ${
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
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-3">
          {!detailsReady && tab !== 'pipeline' ? (
            <div className="space-y-3">
              <div className="h-48 animate-pulse rounded-xl bg-gray-100" />
            </div>
          ) : null}

          {detailsReady && tab === 'transcript' ? (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="space-y-3 pr-1">
                {result?.speaker_segments && result.speaker_segments.length > 0 ? (
                  result.speaker_segments.map(
                    (segment: { speaker: string; text: string; start: number; end?: number }, idx: number) => {
                    const timing = segmentTimingLabel(segment)
                    return (
                    <div
                      key={idx}
                      className={`flex ${isUserSpeaker(segment.speaker) ? 'justify-end' : 'justify-start'}`}
                    >
                      <div className={transcriptBubbleClass(isUserSpeaker(segment.speaker))}>
                        <div className={transcriptMetaClass(isUserSpeaker(segment.speaker))}>
                          <span>{getSpeakerLabel(segment.speaker, result.agent?.name)}</span>
                          {timing ? (
                            <span className="font-normal normal-case tracking-normal tabular-nums">{timing}</span>
                          ) : null}
                        </div>
                        <p className="text-sm leading-relaxed">{segment.text}</p>
                      </div>
                    </div>
                    )
                  },
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
