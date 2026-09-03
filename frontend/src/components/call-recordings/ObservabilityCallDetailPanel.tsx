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
  Download,
  Tag,
  Loader,
  Sparkles,
  X,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

import Button from '../Button'
import ConfirmModal from '../ConfirmModal'
import { apiClient } from '../../lib/api'
import { getObservabilityCallPlaceholder } from '../../lib/observabilityCallQuery'
import RetellCallDetails from './RetellCallDetails'
import VapiCallDetails from './VapiCallDetails'
import VobizCallDetails from './VobizCallDetails'
import { ObservabilityCall } from '../../types/api'
import { useRecordingPresignedUrl } from '../../hooks/useRecordingPresignedUrl'
import { CallAgentLink } from '../../pages/observability/CallAgentLink'
import { EndReasonBadge, EventBadge, PlatformBadge } from '../../pages/observability/observabilityCallUi'

const LIVE_EVENTS = new Set([
  'outbound_initiated',
  'ringing',
  'call_started',
  'call_in_progress',
  'in-progress',
  'answered',
])

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
    Array<{ role: string; content: string; timestamp?: string }>
  >([])

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
    const existing = callRecording?.call_data?.live_transcript
    if (!Array.isArray(existing) || existing.length === 0) return
    setLiveTranscript((prev) => (existing.length >= prev.length ? existing : prev))
  }, [callRecording?.call_data?.live_transcript])

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

  const storageKey = callRecording?.call_data?.recording_s3_key ?? undefined
  const providerRecordingUrl = callRecording?.call_data?.recording_url ?? null
  const hasStorageRecording = !!storageKey

  const { data: presignedRecording, isLoading: presignedLoading } =
    useRecordingPresignedUrl(storageKey)

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
  const liveTranscriptEntries: Array<{
    role: string
    content: string
    timestamp?: string
    start_time?: number
  }> = Array.isArray(callData?.live_transcript) ? callData.live_transcript : []
  const messagesFromLive = liveTranscriptEntries
    .filter((entry) => entry?.content)
    .map((entry) => ({
      role: entry.role === 'user' ? 'user' : 'assistant',
      content: entry.content,
      start_time:
        entry.start_time ?? (entry.timestamp ? new Date(entry.timestamp).getTime() : undefined),
    }))
  const messages: Array<{ role: string; content: string; start_time?: number }> | undefined =
    Array.isArray(callData?.messages) && callData.messages.length > 0
      ? callData.messages
      : messagesFromLive.length > 0
        ? messagesFromLive
        : undefined
  const playbackUrl = presignedRecording?.url || providerRecordingUrl
  const audioLoading = hasStorageRecording && presignedLoading && !playbackUrl
  const isLiveCall =
    callRecording.is_live || LIVE_EVENTS.has((callRecording.call_event || '').toLowerCase())

  const toTranscriptTurn = (entry: { role: string; content: string; start_time?: number }) => ({
    role: entry.role === 'user' ? ('user' as const) : ('agent' as const),
    content: entry.content,
    start_time: entry.start_time,
  })

  const persistedTurns = (messages || messagesFromLive).map(toTranscriptTurn)
  const liveTurns = liveTranscript
    .filter((entry) => entry?.content)
    .map((entry) =>
      toTranscriptTurn({
        role: entry.role,
        content: entry.content,
        start_time: entry.timestamp ? new Date(entry.timestamp).getTime() : undefined,
      }),
    )

  const transcriptTurns = isLiveCall && liveTurns.length > 0 ? liveTurns : persistedTurns
  const hasTranscript = transcriptTurns.length > 0

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

  const formatMessageTime = (timestamp: number): string =>
    new Date(timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })

  const duration = computeDuration()

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

        <div className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
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
              {callRecording.created_at
                ? new Date(callRecording.created_at).toLocaleString()
                : 'N/A'}
            </p>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5 space-y-5">
        {fetchError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {fetchError}
          </div>
        ) : null}
        {!detailsReady ? (
          <div className="space-y-3">
            <div className="h-40 animate-pulse rounded-xl bg-gray-100" />
            <div className="h-56 animate-pulse rounded-xl bg-gray-100" />
          </div>
        ) : (
          <>
        {callRecording.provider_platform === 'retell' && callData ? (
          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <RetellCallDetails callData={callData} hideTranscript={hasTranscript} />
          </section>
        ) : null}

        {callRecording.provider_platform === 'vapi' && callData ? (
          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <VapiCallDetails callData={callData} hideTranscript={hasTranscript} />
          </section>
        ) : null}

        {callRecording.provider_platform === 'vobiz' && callData ? (
          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <VobizCallDetails callData={callData} />
          </section>
        ) : null}

        {(hasStorageRecording || providerRecordingUrl) && !isLiveCall ? (
          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <h3 className="mb-3 text-sm font-semibold text-gray-900">Call recording</h3>
            {audioLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <Loader className="h-4 w-4 animate-spin" />
                Loading recording…
              </div>
            ) : playbackUrl ? (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <audio controls src={playbackUrl} preload="metadata" className="w-full max-w-xl" />
                <a
                  href={playbackUrl}
                  download={`call_${callRecording.call_short_id}.wav`}
                  className="inline-flex items-center gap-2 text-sm text-primary-600 hover:text-primary-800"
                >
                  <Download className="h-4 w-4" />
                  Download
                </a>
              </div>
            ) : null}
          </section>
        ) : null}

        {hasTranscript || isLiveCall ? (
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <div className="flex h-[480px] flex-col rounded-xl border border-gray-200 bg-white">
                <div className="flex shrink-0 items-center justify-between border-b border-gray-100 px-4 py-3">
                  <div className="flex items-center gap-2">
                    <MessageSquare className="h-4 w-4 text-primary-500" />
                    <span className="text-sm font-medium text-gray-900">
                      {isLiveCall ? 'Live transcript' : 'Transcript'}
                    </span>
                    {isLiveCall ? (
                      <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800 animate-pulse">
                        Live
                      </span>
                    ) : null}
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {transcriptTurns.length} turns
                    </span>
                  </div>
                </div>
                <div className="flex-1 space-y-3 overflow-y-auto p-4">
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
                          <div
                            className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
                              isUser
                                ? 'rounded-br-sm bg-primary-600 text-white'
                                : 'rounded-bl-sm border border-gray-200 bg-gray-50 text-gray-800'
                            }`}
                          >
                            <div
                              className={`mb-0.5 flex items-center gap-2 ${
                                isUser ? 'text-primary-200' : 'text-gray-400'
                              }`}
                            >
                              <span className="text-[10px] font-semibold uppercase tracking-wider">
                                {isUser ? 'Caller' : 'Agent'}
                              </span>
                              {turn.start_time ? (
                                <span className="text-[10px] tabular-nums">
                                  {formatMessageTime(turn.start_time)}
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
            </div>

            <div className="space-y-3 rounded-xl border border-gray-200 bg-white p-5">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
                <Phone className="h-4 w-4 text-primary-500" />
                Call summary
              </h3>
              {callData?.startedAt || callData?.started_at ? (
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                    Started
                  </p>
                  <p className="text-sm text-gray-900">
                    {new Date(callData.startedAt || callData.started_at!).toLocaleString()}
                  </p>
                </div>
              ) : null}
              {callData?.endedAt || callData?.ended_at ? (
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                    Ended
                  </p>
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
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                    End reason
                  </p>
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
          </div>
        ) : null}
          </>
        )}
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
