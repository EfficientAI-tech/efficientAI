import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  MessageSquare,
  Sparkles,
  Activity,
  X,
  DollarSign,
  Clock,
  ListTree,
  BarChart3,
  Layers,
} from 'lucide-react'
import { isVoiceAiProviderPlatform } from '../../lib/callDetailRouting'
import VoiceAiCallDetailPanel, {
  ProviderSummaryChips,
  type VoiceAiMetricsSection,
} from './VoiceAiCallDetailPanel'
import { apiClient } from '../../lib/api'
import { formatMessageTiming } from '../../lib/callTranscriptTiming'
import { transcriptBubbleClass, transcriptMetaClass } from './transcriptBubbleStyles'
import { resolveEvaluatorAudioPlayback } from '../../lib/callDetailRouting'
import { getEvaluatorResultPlaceholder } from '../../lib/evaluatorResultQuery'
import { hasEvaluatorResultRecording } from '../../lib/recordingUrls'
import {
  prefetchCallRecordingAudio,
  prefetchEvaluatorRecordingAudio,
  prefetchObservabilityCallAudio,
} from '../../lib/waveformAudioCache'
import CallWaveformPlayer from './CallWaveformPlayer'
import SyntheticCallTracePanel, { type SyntheticTraceDetailTab } from './SyntheticCallTracePanel'
import LiveTranscriptPanel, { type LiveTranscriptTurn } from './LiveTranscriptPanel'
import {
  CallDetailScopeTags,
  evaluatorDrawerScopeTags,
  type EvaluatorCallScope,
} from './callDetailScope'

type DrawerTab =
  | 'transcript'
  | 'analysis'
  | 'cost'
  | 'latency'
  | 'logs'
  | SyntheticTraceDetailTab

const PIPELINE_TAB_IDS: SyntheticTraceDetailTab[] = ['trace', 'waterfall', 'timeline', 'spans']

const BASE_TABS: Array<{ id: DrawerTab; label: string; icon: typeof MessageSquare }> = [
  { id: 'transcript', label: 'Transcript', icon: MessageSquare },
  { id: 'analysis', label: 'Analysis', icon: Sparkles },
]

const PROVIDER_METRIC_TABS: Array<{ id: DrawerTab; label: string; icon: typeof MessageSquare }> = [
  { id: 'cost', label: 'Cost', icon: DollarSign },
  { id: 'latency', label: 'Latency', icon: Clock },
  { id: 'logs', label: 'Logs', icon: ListTree },
]

const PIPELINE_SUB_TABS: Array<{ id: SyntheticTraceDetailTab; label: string; icon: typeof Activity }> = [
  { id: 'trace', label: 'Trace', icon: Activity },
  { id: 'waterfall', label: 'Waterfall', icon: BarChart3 },
  { id: 'timeline', label: 'Timeline', icon: Clock },
  { id: 'spans', label: 'Spans', icon: Layers },
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

function getSpeakerLabel(speaker: string, agentName?: string, personaName?: string): string {
  if (isUserSpeaker(speaker)) return personaName?.trim() || 'Caller'
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

  const { data: result, isLoading, isFetching, isError, error } = useQuery({
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

  const syntheticTraceId =
    typeof (result as { synthetic_call_trace_id?: string | null } | undefined)?.synthetic_call_trace_id ===
    'string'
      ? (result as { synthetic_call_trace_id: string }).synthetic_call_trace_id
      : undefined
  const callShortIdFromData =
    typeof result?.call_data?.call_short_id === 'string' ? result.call_data.call_short_id : undefined

  const { data: traceFallback } = useQuery({
    queryKey: ['synthetic-call-trace', syntheticTraceId, 'transcript-fallback'],
    queryFn: () => apiClient.getSyntheticCallTrace(syntheticTraceId!, false),
    enabled: Boolean(syntheticTraceId && !hasPersistedTranscript),
    retry: false,
  })

  const { data: hasPipelineTrace = false } = useQuery({
    queryKey: [
      'evaluator-pipeline-trace-available',
      evaluatorResultId,
      syntheticTraceId,
      callShortIdFromData,
    ],
    queryFn: async () => {
      if (syntheticTraceId) {
        try {
          await apiClient.getSyntheticCallTrace(syntheticTraceId, false)
          return true
        } catch {
          return false
        }
      }
      if (callShortIdFromData) {
        try {
          await apiClient.getSyntheticCallTraceByCallShortId(callShortIdFromData, false)
          return true
        } catch {
          return false
        }
      }
      if (result?.persona || result?.scenario) {
        try {
          await apiClient.getSyntheticCallTraceForResult(evaluatorResultId, false)
          return true
        } catch {
          return false
        }
      }
      return false
    },
    enabled: Boolean(evaluatorResultId && result),
    retry: false,
    staleTime: 60_000,
  })

  const showProviderTab = Boolean(
    result && isVoiceAiProviderPlatform(result.provider_platform) && result.call_data,
  )

  const visibleTabs = useMemo(() => {
    const tabs = [...BASE_TABS]
    if (showProviderTab) tabs.push(...PROVIDER_METRIC_TABS)
    if (hasPipelineTrace) tabs.push(...PIPELINE_SUB_TABS)
    return tabs
  }, [hasPipelineTrace, showProviderTab])

  useEffect(() => {
    if (PIPELINE_TAB_IDS.includes(tab as SyntheticTraceDetailTab) && !hasPipelineTrace) {
      setTab('transcript')
    }
    if ((tab === 'cost' || tab === 'latency' || tab === 'logs') && !showProviderTab) {
      setTab('transcript')
    }
  }, [tab, hasPipelineTrace, showProviderTab])

  const providerRecording = useMemo(
    () =>
      result
        ? {
            provider_platform: result.provider_platform,
            call_data: result.call_data as Record<string, unknown>,
          }
        : null,
    [result],
  )

  const traceSegments = useMemo(
    () => segmentsFromTraceTurns((traceFallback?.turns ?? []) as Array<Record<string, unknown>>),
    [traceFallback?.turns],
  )

  const speakerSegments = persistedSegments.length > 0 ? persistedSegments : traceSegments
  const personaName = result?.persona?.name
  const transcription =
    String(result?.transcription ?? '').trim() ||
    (speakerSegments.length > 0
      ? speakerSegments
          .map((seg) => `${getSpeakerLabel(seg.speaker, result?.agent?.name, personaName)}: ${seg.text}`)
          .join('\n')
      : '')

  const isLiveCall = Boolean(
    result &&
      IN_PROGRESS_STATUSES.has(String(result.status ?? '').toLowerCase()) &&
      (result.call_event === 'call_started' || result.call_event === 'call_in_progress'),
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
      eventSource = apiClient.openAuthenticatedEventSource(
        `/api/v1/evaluator-results/${evaluatorResultId}/live-events`,
      )
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

  const audioPlayback = useMemo(() => {
    if (!result) return {}
    return resolveEvaluatorAudioPlayback({
      callShortId: callShortIdFromData,
      providerPlatform: result.provider_platform,
      callRecordingSource: (result as { call_recording_source?: string | null }).call_recording_source,
      evaluatorResultId,
    })
  }, [result, callShortIdFromData, evaluatorResultId])

  useEffect(() => {
    if (!result) return
    if (audioPlayback.callShortId) {
      prefetchCallRecordingAudio(audioPlayback.callShortId, false)
      return
    }
    if (audioPlayback.observabilityCallShortId) {
      prefetchObservabilityCallAudio(audioPlayback.observabilityCallShortId)
      return
    }
    if (hasEvaluatorResultRecording(result)) {
      prefetchEvaluatorRecordingAudio(evaluatorResultId)
    }
  }, [result, audioPlayback, evaluatorResultId])

  if (!result && (isLoading || isFetching)) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8">
        <div className="h-10 w-10 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
        <p className="text-sm text-gray-500">Loading call details…</p>
      </div>
    )
  }

  if (!result && !isLoading && !isFetching) {
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
  const transcriptLoading = (isLoading || isFetching) && !hasTranscript
  const evaluationInProgress = Boolean(
    result && IN_PROGRESS_STATUSES.has(String(result.status ?? '').toLowerCase()),
  )
  const analysisLoading =
    tab === 'analysis' &&
    (evaluationInProgress ||
      ((isLoading || isFetching) &&
        !callAnalysis.call_summary &&
        callAnalysis.call_successful == null &&
        callAnalysis.user_sentiment === 'Neutral'))

  const callScope: EvaluatorCallScope = {
    agentName: result?.agent?.name,
    personaName: result?.persona?.name,
    personaTtsLine:
      result?.persona?.tts_provider || result?.persona?.tts_voice_name
        ? [result.persona.tts_provider, result.persona.tts_voice_name].filter(Boolean).join(' · ')
        : null,
    platform: result?.provider_platform,
  }
  const tabScope = evaluatorDrawerScopeTags(tab, callScope)
  const providerBillingScope = {
    subjectLabel: result?.agent?.name,
    personaName: result?.persona?.name,
    personaTtsLine: callScope.personaTtsLine,
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-50">
      <div className="shrink-0 border-b border-gray-200 bg-white px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-gray-900">Call details</h2>
            <p className="mt-0.5 text-xs text-gray-500">
              Result{' '}
              <span className="font-mono font-medium text-primary-600">
                {result?.result_id ?? evaluatorResultId}
              </span>
              {result?.agent?.name ? (
                <>
                  {' '}
                  · <span className="text-gray-700">{result.agent.name}</span>
                </>
              ) : null}
            </p>
            {showProviderTab && providerRecording ? (
              <div className="mt-3">
                <ProviderSummaryChips recording={providerRecording} />
              </div>
            ) : null}
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
        <div className="shrink-0 space-y-2.5 border-b border-gray-200 bg-gray-50 px-5 pb-0 pt-3">
          {fetchError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              {fetchError}
            </div>
          ) : null}

          <CallWaveformPlayer
            evaluatorResultId={audioPlayback.evaluatorResultId}
            callShortId={audioPlayback.callShortId}
            observabilityCallShortId={audioPlayback.observabilityCallShortId}
            callData={result?.call_data}
            platform={result?.provider_platform}
          />

          <div className="-mx-5 flex flex-nowrap gap-0.5 overflow-x-auto border-t border-gray-200 bg-white px-5 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {visibleTabs.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`inline-flex shrink-0 items-center gap-1.5 border-b-2 px-2.5 py-2 text-sm font-medium transition-colors ${
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
          {tab !== 'cost' && tab !== 'latency' && tab !== 'logs' ? (
            <CallDetailScopeTags tags={tabScope.tags} hint={tabScope.hint} />
          ) : null}
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
                              <span>
                                {getSpeakerLabel(segment.speaker, result?.agent?.name, personaName)}
                              </span>
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
            analysisLoading ? (
              <div className="space-y-3">
                <div className="flex items-center justify-center gap-2 py-8 text-sm text-gray-500">
                  <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
                  {evaluationInProgress ? 'Evaluation in progress…' : 'Loading analysis…'}
                </div>
                <div className="h-32 animate-pulse rounded-xl bg-gray-100" />
              </div>
            ) : (
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
              {result?.call_data?.endedReason ? (
                <div className="mt-4 rounded-lg bg-gray-50 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                    End reason
                  </p>
                  <p className="mt-1 text-sm text-gray-900">
                    {String(result.call_data.endedReason).replace(/-/g, ' ')}
                  </p>
                </div>
              ) : null}
              {!callAnalysis.call_summary &&
              callAnalysis.call_successful == null &&
              callAnalysis.user_sentiment === 'Neutral' &&
              !result?.call_data?.endedReason ? (
                <p className="mt-4 text-center text-sm text-gray-500">No call analysis available.</p>
              ) : null}
            </div>
            )
          ) : null}

          {showProviderTab && result && (tab === 'cost' || tab === 'latency' || tab === 'logs') ? (
            <VoiceAiCallDetailPanel
              recording={{
                provider_platform: result.provider_platform,
                provider_call_id: result.provider_call_id,
                call_data: result.call_data as Record<string, unknown>,
                status: result.status,
              }}
              callShortId={audioPlayback.callShortId ?? callShortIdFromData ?? ''}
              hideWaveform
              embeddedSection={tab as VoiceAiMetricsSection}
              billingScope={providerBillingScope}
            />
          ) : null}

          {PIPELINE_TAB_IDS.includes(tab as SyntheticTraceDetailTab) && hasPipelineTrace ? (
            <SyntheticCallTracePanel
              evaluatorResultId={evaluatorResultId}
              traceId={syntheticTraceId}
              callShortId={callShortIdFromData}
              embedded
              hideTabBar
              activeTab={tab as SyntheticTraceDetailTab}
            />
          ) : null}
        </div>
      </div>
    </div>
  )
}
