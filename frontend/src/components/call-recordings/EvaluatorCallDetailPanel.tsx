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
import LiveTranscriptPanel, { type LiveTranscriptTurn } from './LiveTranscriptPanel'

type DrawerTab = 'transcript' | 'analysis' | 'pipeline'

const TABS: Array<{ id: DrawerTab; label: string; icon: typeof MessageSquare }> = [
  { id: 'transcript', label: 'Transcript', icon: MessageSquare },
  { id: 'analysis', label: 'Analysis', icon: Sparkles },
  { id: 'pipeline', label: 'Pipeline', icon: Activity },
]

const IN_PROGRESS_STATUSES = new Set([
  'queued',
  'transcribing',
  'evaluating',
  'fetching_details',
  'call_started',
  'call_in_progress',
  'in_progress',
])

type SpeakerSegment = { speaker: string; text: string; start: number; end?: number }

function segmentTimingLabel(segment: { start: number; end?: number }): string | null {
  return formatMessageTiming(segment.start, segment.end)
}

function isUserSpeaker(speaker: string): boolean {
  const normalized = speaker.trim().toLowerCase()
  return (
    normalized === 'speaker 1' ||
    normalized === 'user' ||
    normalized === 'caller' ||
    normalized === 'customer'
  )
}

function getSpeakerLabel(speaker: string, agentName?: string): string {
  if (isUserSpeaker(speaker)) return 'Caller'
  if (['assistant', 'speaker 2', 'bot', 'agent'].includes(speaker.trim().toLowerCase())) {
    return agentName || 'Agent'
  }
  return agentName || 'Agent'
}

function segmentsFromTraceTurns(turns: Array<Record<string, unknown>>): SpeakerSegment[] {
  const segments: SpeakerSegment[] = []
  for (const turn of turns) {
    const turnNumber = Number(turn.turn_number ?? segments.length + 1)
    const extra =
      turn.extra && typeof turn.extra === 'object'
        ? (turn.extra as Record<string, unknown>)
        : {}
    const userText = String(extra.user_text ?? '').trim()
    const assistantText = String(extra.assistant_text ?? '').trim()
    const transcript = String(turn.transcript ?? '').trim()
    if (userText) {
      segments.push({ speaker: 'user', text: userText, start: turnNumber, end: turnNumber })
    }
    if (assistantText) {
      segments.push({ speaker: 'assistant', text: assistantText, start: turnNumber, end: turnNumber })
    }
    if (!userText && !assistantText && transcript) {
      const userMatch = transcript.match(/^User:\s*(.+)$/m)
      const assistantMatch = transcript.match(/^Assistant:\s*(.+)$/m)
      if (userMatch) {
        segments.push({ speaker: 'user', text: userMatch[1].trim(), start: turnNumber, end: turnNumber })
      }
      if (assistantMatch) {
        segments.push({
          speaker: 'assistant',
          text: assistantMatch[1].trim(),
          start: turnNumber,
          end: turnNumber,
        })
      }
      if (!userMatch && !assistantMatch) {
        segments.push({ speaker: 'assistant', text: transcript, start: turnNumber, end: turnNumber })
      }
    }
  }
  return segments
}

export default function EvaluatorCallDetailPanel({
  evaluatorResultId,
  onClose,
}: {
  evaluatorResultId: string
  onClose?: () => void
}) {
  const [tab, setTab] = useState<DrawerTab>('transcript')
  const [liveTranscript, setLiveTranscript] = useState<LiveTranscriptTurn[]>([])
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

  const persistedSegments = (result?.speaker_segments ?? []) as SpeakerSegment[]
  const hasPersistedTranscript = Boolean(
    persistedSegments.length > 0 || String(result?.transcription ?? '').trim(),
  )

  const { data: traceFallback } = useQuery({
    queryKey: ['synthetic-call-trace', evaluatorResultId, 'transcript-fallback'],
    queryFn: () => apiClient.getSyntheticCallTraceForResult(evaluatorResultId),
    enabled: Boolean(evaluatorResultId) && !isFetching && !hasPersistedTranscript,
    retry: false,
  })

  const traceSegments = useMemo(
    () => segmentsFromTraceTurns((traceFallback?.turns ?? []) as Array<Record<string, unknown>>),
    [traceFallback?.turns],
  )

  const speakerSegments = persistedSegments.length > 0 ? persistedSegments : traceSegments
  const transcription =
    String(result?.transcription ?? '').trim() ||
    (speakerSegments.length > 0
      ? speakerSegments.map((seg) => `${getSpeakerLabel(seg.speaker, result?.agent?.name)}: ${seg.text}`).join('\n')
      : '')

  const isLiveCall = Boolean(
    result &&
      IN_PROGRESS_STATUSES.has(String(result.status ?? '').toLowerCase()) &&
      (result.call_event === 'call_started' ||
        result.call_event === 'call_in_progress' ||
        !result.call_event),
  )

  useEffect(() => {
    setLiveTranscript([])
  }, [evaluatorResultId])

  useEffect(() => {
    const existing = result?.call_data?.live_transcript
    if (!Array.isArray(existing) || existing.length === 0) return
    setLiveTranscript(
      existing.map((entry: Record<string, unknown>) => ({
        role: String(entry.role ?? 'user'),
        content: String(entry.content ?? entry.message ?? entry.text ?? ''),
        timestamp: typeof entry.timestamp === 'string' ? entry.timestamp : undefined,
        start_time: typeof entry.start_time === 'number' ? entry.start_time : undefined,
      })),
    )
  }, [result?.call_data?.live_transcript, evaluatorResultId])

  useEffect(() => {
    if (!evaluatorResultId || !result || !isLiveCall) return

    let eventSource: EventSource | null = null
    try {
      eventSource = new EventSource(apiClient.getEvaluatorResultLiveEventsUrl(evaluatorResultId))
      eventSource.onmessage = (event) => {
        try {
          const entry = JSON.parse(event.data)
          setLiveTranscript((prev) => [
            ...prev,
            {
              role: String(entry.role ?? 'user'),
              content: String(entry.content ?? entry.message ?? entry.text ?? ''),
              timestamp: typeof entry.timestamp === 'string' ? entry.timestamp : undefined,
              start_time: typeof entry.start_time === 'number' ? entry.start_time : undefined,
            },
          ])
        } catch {
          // ignore malformed events
        }
      }
    } catch {
      // polling still updates live_transcript from call_data
    }

    return () => {
      eventSource?.close()
    }
  }, [evaluatorResultId, isLiveCall, result?.status, result?.call_event])

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

  if (!result && isFetching) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="h-10 w-10 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
      </div>
    )
  }

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

  const showLiveTranscript = isLiveCall && liveTranscript.length > 0
  const hasTranscript = Boolean(speakerSegments.length > 0 || transcription || showLiveTranscript)
  const transcriptLoading = isFetching && !hasTranscript

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
          {tab === 'transcript' ? (
            transcriptLoading ? (
              <div className="space-y-3">
                <div className="h-48 animate-pulse rounded-xl bg-gray-100" />
              </div>
            ) : showLiveTranscript ? (
              <LiveTranscriptPanel
                turns={liveTranscript}
                isLive={isLiveCall}
                agentName={result?.agent?.name || 'Agent'}
                heightClass="min-h-[320px]"
                emptyMessage="Waiting for speech…"
              />
            ) : (
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <div className="space-y-3 pr-1">
                  {speakerSegments.length > 0 ? (
                    speakerSegments.map((segment, idx) => {
                      const timing = segmentTimingLabel(segment)
                      return (
                        <div
                          key={idx}
                          className={`flex ${isUserSpeaker(segment.speaker) ? 'justify-end' : 'justify-start'}`}
                        >
                          <div className={transcriptBubbleClass(isUserSpeaker(segment.speaker))}>
                            <div className={transcriptMetaClass(isUserSpeaker(segment.speaker))}>
                              <span>{getSpeakerLabel(segment.speaker, result?.agent?.name)}</span>
                              {timing ? (
                                <span className="font-normal normal-case tracking-normal tabular-nums">
                                  {timing}
                                </span>
                              ) : null}
                            </div>
                            <p className="text-sm leading-relaxed">{segment.text}</p>
                          </div>
                        </div>
                      )
                    })
                  ) : transcription ? (
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
                      {transcription}
                    </p>
                  ) : isLiveCall ? (
                    <LiveTranscriptPanel
                      turns={liveTranscript}
                      isLive
                      agentName={result?.agent?.name || 'Agent'}
                      heightClass="min-h-[240px]"
                    />
                  ) : (
                    <p className="py-8 text-center text-sm text-gray-500">No transcript available.</p>
                  )}
                </div>
              </div>
            )
          ) : null}

          {tab === 'analysis' ? (
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
            <SyntheticCallTracePanel
              evaluatorResultId={evaluatorResultId}
              callShortId={callShortId}
              embedded
            />
          ) : null}
        </div>
      </div>
    </div>
  )
}
