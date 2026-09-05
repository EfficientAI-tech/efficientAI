import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Phone,
  Clock,
  PhoneIncoming,
  PhoneOutgoing,
  MessageSquare,
  Trash2,
  Tag,
  Sparkles,
  Server,
  X,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

import Button from '../Button'
import ConfirmModal from '../ConfirmModal'
import { apiClient } from '../../lib/api'
import {
  formatMessageTiming,
  normalizeEpochSeconds,
  offsetSecondsFromCallStart,
  sanitizeCallOffsetSeconds,
} from '../../lib/callTranscriptTiming'
import CallWaveformPlayer from './CallWaveformPlayer'
import { getObservabilityCallPlaceholder } from '../../lib/observabilityCallQuery'
import { prefetchObservabilityCallAudio } from '../../lib/waveformAudioCache'
import RetellCallDetails from './RetellCallDetails'
import VapiCallDetails from './VapiCallDetails'
import VobizCallDetails from './VobizCallDetails'
import { ObservabilityCall } from '../../types/api'
import { CallAgentLink } from '../../pages/observability/CallAgentLink'
import { EndReasonBadge, EventBadge, PlatformBadge } from '../../pages/observability/observabilityCallUi'
import { transcriptBubbleClass, transcriptMetaClass } from './transcriptBubbleStyles'

const LIVE_EVENTS = new Set([
  'outbound_initiated',
  'ringing',
  'call_started',
  'call_in_progress',
  'in-progress',
  'answered',
])

type DrawerTab = 'transcript' | 'summary' | 'provider'

interface TranscriptMessage {
  role: 'user' | 'agent'
  content: string
  timingLabel: string | null
}

interface RawTranscriptMessage {
  role?: string
  content?: string
  start_time?: number
  end_time?: number
  seconds_from_start?: number
  timestamp?: string
}

export default function ObservabilityCallDetailPanel({
  callShortId,
  onClose,
}: {
  callShortId: string
  onClose?: () => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showDelete, setShowDelete] = useState(false)
  const [showEvalModal, setShowEvalModal] = useState(false)
  const [selectedEvaluator, setSelectedEvaluator] = useState('')
  const [liveTranscript, setLiveTranscript] = useState<
    Array<{ role: string; content: string; timestamp?: string; start_time?: number; end_time?: number }>
  >([])
  const [tab, setTab] = useState<DrawerTab>('transcript')

  const { data: callRecording, isFetching, isError, error } = useQuery<ObservabilityCall>({
    queryKey: ['observability-call', callShortId],
    queryFn: () => apiClient.getObservabilityCall(callShortId),
    enabled: Boolean(callShortId),
    placeholderData: () => getObservabilityCallPlaceholder(queryClient, callShortId),
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return false
      const isLive = data.is_live || LIVE_EVENTS.has((data.call_event || '').toLowerCase())
      return isLive ? 3000 : false
    },
  })

  useEffect(() => {
    setLiveTranscript([])
  }, [callShortId])

  useEffect(() => {
    const existing = callRecording?.call_data?.live_transcript
    if (!Array.isArray(existing) || existing.length === 0) return
    setLiveTranscript(existing)
  }, [callRecording?.call_data?.live_transcript, callShortId])

  useEffect(() => {
    if (callRecording?.call_event === 'call_ended') {
      queryClient.invalidateQueries({ queryKey: ['observability-call', callShortId] })
    }
  }, [callRecording?.call_event, callShortId, queryClient])


  useEffect(() => {
    if (!callShortId || !callRecording) return
    const isLive =
      callRecording.is_live || LIVE_EVENTS.has((callRecording.call_event || '').toLowerCase())
    if (!isLive) return

    let eventSource: EventSource | null = null
    try {
      eventSource = new EventSource(apiClient.getObservabilityCallLiveEventsUrl(callShortId))
      eventSource.onmessage = (event) => {
        try {
          const entry = JSON.parse(event.data)
          setLiveTranscript((prev) => [...prev, entry])
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
  }, [callShortId, callRecording?.call_event, callRecording?.is_live])

  useEffect(() => {
    if (!callShortId || !callRecording) return
    const isLive =
      callRecording.is_live || LIVE_EVENTS.has((callRecording.call_event || '').toLowerCase())
    if (isLive) return
    if (callRecording.call_data?.recording_s3_key || callRecording.call_data?.recording_url) {
      prefetchObservabilityCallAudio(callShortId)
    }
  }, [callShortId, callRecording?.call_data, callRecording?.call_event, callRecording?.is_live])

  const providerRecordingUrl = callRecording?.call_data?.recording_url ?? null
  const hasStorageRecording = Boolean(callRecording?.call_data?.recording_s3_key)

  const { data: evaluators = [] } = useQuery({
    queryKey: ['evaluators'],
    queryFn: () => apiClient.listEvaluators(),
    enabled: showEvalModal,
  })

  const deleteMutation = useMutation({
    mutationFn: () => apiClient.deleteObservabilityCall(callShortId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['observability-calls'] })
      onClose?.()
    },
  })

  const evaluateMutation = useMutation({
    mutationFn: (evaluatorId: string) =>
      apiClient.evaluateObservabilityCall(callShortId, evaluatorId),
    onSuccess: (data) => {
      setShowEvalModal(false)
      setSelectedEvaluator('')
      navigate(`/results/${data.result_id}`)
    },
  })

  if (!callRecording && !isFetching) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="text-sm font-medium text-rose-800">Call not found</p>
        {onClose ? (
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        ) : null}
      </div>
    )
  }

  if (!callRecording) return null

  const detailsReady = Boolean(callRecording.call_data)
  const fetchError =
    isError && error
      ? (error as { response?: { data?: { detail?: string } }; message?: string }).response?.data
          ?.detail ||
        (error as { message?: string }).message ||
        'Failed to load call'
      : null

  const callData = callRecording.call_data
  const startedAt = callData?.startedAt || callData?.started_at
  const callStartMs = startedAt ? new Date(startedAt).getTime() : undefined
  const callStartSec = callStartMs && !Number.isNaN(callStartMs) ? callStartMs : undefined

  const messageOffsetSec = (entry: RawTranscriptMessage): number | undefined => {
    if (entry.seconds_from_start != null) return entry.seconds_from_start
    const raw = entry.start_time
    if (raw == null) return undefined
    if (raw > 1e10) {
      if (callStartSec == null) return undefined
      return offsetSecondsFromCallStart(raw, callStartSec)
    }
    return normalizeEpochSeconds(raw)
  }

  const toTranscriptMessage = (entry: RawTranscriptMessage): TranscriptMessage => {
    const offsetSec = sanitizeCallOffsetSeconds(messageOffsetSec(entry))
    const startSec = sanitizeCallOffsetSeconds(
      normalizeEpochSeconds(entry.start_time ?? entry.seconds_from_start),
    )
    const endSec = sanitizeCallOffsetSeconds(normalizeEpochSeconds(entry.end_time))
    const timingLabel = formatMessageTiming(offsetSec ?? startSec, endSec)
    return {
      role: entry.role === 'user' ? 'user' : 'agent',
      content: entry.content || '',
      timingLabel,
    }
  }

  const liveTranscriptEntries: RawTranscriptMessage[] = Array.isArray(callData?.live_transcript)
    ? callData.live_transcript
    : []
  const messagesFromLive = liveTranscriptEntries
    .filter((entry) => entry?.content)
    .map((entry) => ({
      role: entry.role === 'user' ? 'user' : 'assistant',
      content: entry.content,
      start_time:
        entry.start_time ?? (entry.timestamp ? new Date(entry.timestamp).getTime() : undefined),
      end_time: entry.end_time,
      timestamp: entry.timestamp,
    }))
  const rawMessages: RawTranscriptMessage[] | undefined =
    Array.isArray(callData?.messages) && callData.messages.length > 0
      ? (callData.messages as RawTranscriptMessage[])
      : messagesFromLive.length > 0
        ? messagesFromLive
        : undefined
  const hasRecording = hasStorageRecording || Boolean(providerRecordingUrl)
  const isLiveCall =
    callRecording.is_live || LIVE_EVENTS.has((callRecording.call_event || '').toLowerCase())

  const persistedTurns = (rawMessages || messagesFromLive).map(toTranscriptMessage)
  const liveTurns = liveTranscript
    .filter((entry) => entry?.content)
    .map((entry) =>
      toTranscriptMessage({
        role: entry.role,
        content: entry.content,
        start_time: entry.start_time ?? (entry.timestamp ? new Date(entry.timestamp).getTime() : undefined),
        end_time: entry.end_time,
        timestamp: entry.timestamp,
      }),
    )

  const transcriptTurns = isLiveCall && liveTurns.length > 0 ? liveTurns : persistedTurns
  const hasTranscript = transcriptTurns.length > 0
  const hasProviderDetails = ['retell', 'vapi', 'vobiz'].includes(callRecording.provider_platform || '')

  const tabs: Array<{ id: DrawerTab; label: string; icon: typeof MessageSquare }> = []
  if (hasTranscript || isLiveCall) {
    tabs.push({ id: 'transcript', label: 'Transcript', icon: MessageSquare })
  }
  tabs.push({ id: 'summary', label: 'Summary', icon: Phone })
  if (hasProviderDetails) {
    tabs.push({ id: 'provider', label: 'Provider', icon: Server })
  }
  const activeTab = tabs.some((item) => item.id === tab) ? tab : (tabs[0]?.id ?? 'summary')

  const computeDuration = (): string | null => {
    const started = callData?.startedAt || callData?.started_at
    const ended = callData?.endedAt || callData?.ended_at
    if (started && ended) {
      const start = new Date(started).getTime()
      const end = new Date(ended).getTime()
      if (!Number.isNaN(start) && !Number.isNaN(end)) {
        const diffSec = Math.floor((end - start) / 1000)
        return `${Math.floor(diffSec / 60)}m ${diffSec % 60}s`
      }
    }
    if (typeof callData?.duration_seconds === 'number') {
      const diffSec = Math.floor(callData.duration_seconds)
      return `${Math.floor(diffSec / 60)}m ${diffSec % 60}s`
    }
    return null
  }

  const duration = computeDuration()

  const summarySection = (
    <div className="space-y-3 rounded-xl border border-gray-200 bg-white p-5">
      <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <div>
          <p className="font-medium text-gray-500">Agent</p>
          <div className="mt-1">
            <CallAgentLink agent={callRecording.agent} callData={callData} />
          </div>
        </div>
        <div>
          <p className="font-medium text-gray-500">Provider call ID</p>
          <p className="mt-1 truncate font-mono text-gray-900" title={callRecording.provider_call_id ?? undefined}>
            {callRecording.provider_call_id || 'N/A'}
          </p>
        </div>
        <div>
          <p className="font-medium text-gray-500">Status</p>
          <p className="mt-1 capitalize text-gray-900">{callRecording.status || '—'}</p>
        </div>
        <div>
          <p className="font-medium text-gray-500">Created</p>
          <p className="mt-1 text-gray-900">
            {callRecording.created_at ? new Date(callRecording.created_at).toLocaleString() : 'N/A'}
          </p>
        </div>
      </div>
      {callData?.startedAt || callData?.started_at ? (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Started</p>
          <p className="text-sm text-gray-900">
            {new Date(callData.startedAt || callData.started_at!).toLocaleString()}
          </p>
        </div>
      ) : null}
      {callData?.endedAt || callData?.ended_at ? (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Ended</p>
          <p className="text-sm text-gray-900">
            {new Date(callData.endedAt || callData.ended_at!).toLocaleString()}
          </p>
        </div>
      ) : null}
      {callData?.from_phone_number || callData?.to_phone_number ? (
        <div className="space-y-2">
          {callData.from_phone_number ? (
            <div className="flex items-center gap-2 text-sm text-gray-700">
              <PhoneOutgoing className="h-3.5 w-3.5 text-gray-400" />
              <span className="font-mono">{callData.from_phone_number}</span>
            </div>
          ) : null}
          {callData.to_phone_number ? (
            <div className="flex items-center gap-2 text-sm text-gray-700">
              <PhoneIncoming className="h-3.5 w-3.5 text-gray-400" />
              <span className="font-mono">{callData.to_phone_number}</span>
            </div>
          ) : null}
        </div>
      ) : null}
      {callData?.endedReason ? (
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400">End reason</p>
          <EndReasonBadge reason={callData.endedReason} />
        </div>
      ) : null}
      {callData?.metadata && Object.keys(callData.metadata).length > 0 ? (
        <div className="space-y-1.5">
          {Object.entries(callData.metadata).map(([key, value]) => (
            <div key={key} className="flex items-start gap-2">
              <Tag className="mt-0.5 h-3 w-3 shrink-0 text-gray-300" />
              <div className="min-w-0 text-xs">
                <span className="text-gray-500">{key}:</span>{' '}
                <span className="font-medium text-gray-800">{String(value)}</span>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-50">
      <div className="shrink-0 border-b border-gray-200 bg-white px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-mono text-xl font-bold tracking-tight text-primary-600">
              #{callRecording.call_short_id}
            </h2>
            <p className="mt-1 text-sm text-gray-600">Provider call from observability ingest</p>
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <EventBadge event={callRecording.call_event ?? undefined} />
              <PlatformBadge platform={callRecording.provider_platform ?? undefined} />
              {duration ? (
                <span className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2.5 py-0.5 text-xs text-gray-600">
                  <Clock className="h-3 w-3 text-gray-400" />
                  {duration}
                </span>
              ) : null}
              {isLiveCall ? (
                <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800 animate-pulse">
                  Live
                </span>
              ) : null}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {hasTranscript ? (
              <Button
                variant="primary"
                size="sm"
                onClick={() => setShowEvalModal(true)}
                leftIcon={<Sparkles className="h-4 w-4" />}
              >
                Evaluate
              </Button>
            ) : null}
            <button
              type="button"
              onClick={() => setShowDelete(true)}
              className="rounded-lg p-2 text-gray-400 hover:bg-rose-50 hover:text-rose-600"
              aria-label="Delete call"
            >
              <Trash2 className="h-4 w-4" />
            </button>
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
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="shrink-0 space-y-2.5 border-b border-gray-200 bg-gray-50 px-5 pb-3 pt-4">
          {fetchError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              {fetchError}
            </div>
          ) : null}
          {hasRecording && !isLiveCall ? <CallWaveformPlayer observabilityCallShortId={callShortId} /> : null}
          <div className="flex flex-nowrap gap-0.5 overflow-x-auto border-b border-gray-200 bg-white px-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {tabs.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`inline-flex shrink-0 items-center gap-1.5 border-b-2 px-2.5 py-1.5 text-sm font-medium transition-colors ${
                  activeTab === id
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
          {!detailsReady ? (
            <div className="space-y-3">
              <div className="h-40 animate-pulse rounded-xl bg-gray-100" />
              <div className="h-56 animate-pulse rounded-xl bg-gray-100" />
            </div>
          ) : null}

          {detailsReady && activeTab === 'transcript' ? (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="space-y-3">
                {transcriptTurns.length === 0 ? (
                  <p className="py-8 text-center text-sm text-gray-500">Waiting for speech…</p>
                ) : (
                  transcriptTurns.map((turn, index) => {
                    const isUser = turn.role === 'user'
                    return (
                      <motion.div
                        key={index}
                        className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                      >
                        <div className={transcriptBubbleClass(isUser)}>
                          <div className={transcriptMetaClass(isUser)}>
                            <span>{isUser ? 'Caller' : 'Agent'}</span>
                            {turn.timingLabel ? (
                              <span className="font-normal normal-case tracking-normal tabular-nums">
                                {turn.timingLabel}
                              </span>
                            ) : null}
                          </div>
                          <p className="text-sm leading-relaxed">{turn.content}</p>
                        </div>
                      </motion.div>
                    )
                  })
                )}
              </div>
            </div>
          ) : null}

          {detailsReady && activeTab === 'summary' ? summarySection : null}

          {detailsReady && activeTab === 'provider' ? (
            <div className="space-y-4">
              {callRecording.provider_platform === 'retell' && callData ? (
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <RetellCallDetails callData={callData} hideTranscript embedded section="full" />
                </div>
              ) : null}
              {callRecording.provider_platform === 'vapi' && callData ? (
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <VapiCallDetails callData={callData} hideTranscript embedded section="full" />
                </div>
              ) : null}
              {callRecording.provider_platform === 'vobiz' && callData ? (
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <VobizCallDetails callData={callData} />
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <ConfirmModal
        title="Delete call"
        description="This will permanently remove this call record."
        isOpen={showDelete}
        isLoading={deleteMutation.isPending}
        onCancel={() => setShowDelete(false)}
        onConfirm={() => deleteMutation.mutate()}
      />

      <AnimatePresence>
        {showEvalModal ? (
          <motion.div
            className="fixed inset-0 z-[110] flex items-center justify-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div
              className="absolute inset-0 bg-gray-500/75"
              onClick={() => {
                setShowEvalModal(false)
                setSelectedEvaluator('')
              }}
            />
            <motion.div
              className="relative mx-4 w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-2xl"
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
            >
              <div className="border-b border-gray-100 px-6 py-5">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900">Run evaluation</h2>
                    <p className="mt-0.5 text-sm text-gray-500">
                      Evaluate call{' '}
                      <span className="font-mono font-semibold">{callRecording.call_short_id}</span>
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setShowEvalModal(false)
                      setSelectedEvaluator('')
                    }}
                    className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>
              <div className="space-y-4 p-6">
                <select
                  value={selectedEvaluator}
                  onChange={(e) => setSelectedEvaluator(e.target.value)}
                  className="w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm focus:border-primary-500 focus:ring-2 focus:ring-primary-500"
                >
                  <option value="">Choose an evaluator…</option>
                  {evaluators.map((evaluator: { id: string; evaluator_id: string; custom_prompt?: string; name?: string; agent_id?: string }) => (
                    <option key={evaluator.id} value={evaluator.id}>
                      {evaluator.evaluator_id} —{' '}
                      {evaluator.custom_prompt
                        ? `Custom: ${evaluator.name || 'Unnamed'}`
                        : `Agent: ${evaluator.agent_id?.substring(0, 8) || '?'}…`}
                    </option>
                  ))}
                </select>
                {evaluateMutation.isError ? (
                  <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
                    {(evaluateMutation.error as { response?: { data?: { detail?: string } } })?.response
                      ?.data?.detail || 'Failed to start evaluation'}
                  </div>
                ) : null}
              </div>
              <div className="flex justify-end gap-3 border-t border-gray-100 bg-gray-50/50 px-6 py-4">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setShowEvalModal(false)
                    setSelectedEvaluator('')
                  }}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => evaluateMutation.mutate(selectedEvaluator)}
                  disabled={!selectedEvaluator || evaluateMutation.isPending}
                  isLoading={evaluateMutation.isPending}
                  leftIcon={!evaluateMutation.isPending ? <Sparkles className="h-4 w-4" /> : undefined}
                >
                  Run evaluation
                </Button>
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  )
}
