import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft, Phone, Clock, PhoneIncoming, PhoneOutgoing,
  MessageSquare, Trash2, Tag,
  Loader, XCircle, Sparkles, X, Download, RotateCw,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts'

import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import { apiClient } from '../../lib/api'
import TraceRecordingPanel from '../../components/observability/TraceRecordingPanel'
import { buildWaveformSegments } from '../../components/observability/waveformSegments'
import {
  buildSpanTree,
  findTurnSpanForTranscriptIndex,
  flattenSpanTree,
} from '../../components/observability/traceDisplay'
import { getIntegrationPlatformLabel, getIntegrationPlatformLogo } from '../../config/providers'
import { IntegrationPlatform, ObservabilityCall, ObservabilityCallTrace } from '../../types/api'
import { useObservabilityCallAudioBlob } from '../../hooks/useObservabilityCallAudioBlob'
import { useRecordingPresignedUrl } from '../../hooks/useRecordingPresignedUrl'
import { CallAgentLink } from './CallAgentLink'

function getTraceFetchErrorDisplay(error: unknown): {
  title: string
  body: string
  hint?: string
} {
  const axiosError = error as { response?: { status?: number; data?: { detail?: string } }; message?: string }
  const status = axiosError.response?.status
  const detail =
    typeof axiosError.response?.data?.detail === 'string'
      ? axiosError.response.data.detail
      : axiosError.message

  if (status === 404) {
    const isSyntheticMissing =
      typeof detail === 'string' &&
      (detail.includes('No trace linked') ||
        detail.toLowerCase().includes('no provider trace') ||
        detail.toLowerCase().includes('no synthetic'))
    return {
      title: isSyntheticMissing ? 'Provider trace not ready' : 'Trace not found in store',
      body:
        detail ||
        (isSyntheticMissing
          ? 'Full Retell/Vapi metrics may not have been pulled yet. Click Refresh on the call to fetch provider report data and synthetic trace.'
          : 'This call has a trace ID, but Tempo has no spans for it. The trace may have expired, been purged, or never exported.'),
      hint: isSyntheticMissing
        ? 'Ensure the call is linked to an agent with a Retell integration, then use Refresh.'
        : 'Run a new voice-bundle test call while Tempo is running and tracing is enabled. Tempo retains traces for 24h by default (see observability/tempo/tempo.yml).',
    }
  }

  if (status === 502) {
    const isConnectionError =
      typeof detail === 'string' &&
      (detail.includes('Could not reach') || detail.toLowerCase().includes('connect'))
    return {
      title: isConnectionError ? 'Trace store unreachable' : 'Trace backend error',
      body: detail || 'The trace query API returned an upstream error.',
      hint: isConnectionError
        ? 'Restart the API after changing config.yml (query_backend / tempo_query_url). For local dev: docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d tempo'
        : 'Ensure Tempo is reachable at tempo_query_url in config.yml. Tempo running in Docker does not guarantee spans were exported to it.',
    }
  }

  return {
    title: 'Could not load trace',
    body: detail || 'An unexpected error occurred while fetching spans.',
    hint:
      'For local dev: docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d tempo',
  }
}

type DetailTab = 'overview' | 'transcript' | 'trace'

function looksLikeRetellCallData(callData: Record<string, unknown> | undefined): boolean {
  if (!callData || typeof callData !== 'object') return false
  return Boolean(
    callData.latency ||
      callData.call_analysis ||
      callData.call_cost ||
      (callData.call_id && Array.isArray(callData.transcript_object)),
  )
}

function looksLikeVapiCallData(callData: Record<string, unknown> | undefined): boolean {
  if (!callData || typeof callData !== 'object') return false
  return Boolean(callData.assistantId || callData.assistant_id || callData.artifact || callData.endedReason)
}

export default function ObservabilityCallDetail() {
  const navigate = useNavigate()
  const { callShortId } = useParams<{ callShortId: string }>()
  const queryClient = useQueryClient()
  const [showDelete, setShowDelete] = useState(false)
  const [showEvalModal, setShowEvalModal] = useState(false)
  const [selectedEvaluator, setSelectedEvaluator] = useState('')
  const [liveTranscript, setLiveTranscript] = useState<
    Array<{ role: string; content: string; timestamp?: string; start_time?: number }>
  >([])
  const [activeTab, setActiveTab] = useState<DetailTab>('overview')
  const [selectedTraceSpanId, setSelectedTraceSpanId] = useState<string | null>(null)
  const [highlightedTranscriptIndex, setHighlightedTranscriptIndex] = useState<number | null>(null)

  const liveEvents = new Set([
    'outbound_initiated',
    'ringing',
    'call_started',
    'call_in_progress',
    'in-progress',
    'answered',
  ])

  const {
    data: callRecording,
    isLoading,
  } = useQuery<ObservabilityCall>({
    queryKey: ['observability-call', callShortId],
    queryFn: () => apiClient.getObservabilityCall(callShortId!),
    enabled: !!callShortId,
    refetchInterval: (query) => {
      const data = query.state.data as any
      if (!data) return false
      const isLive = data.is_live || liveEvents.has((data.call_event || '').toLowerCase())
      return isLive ? 3000 : false
    },
  })

  const linkedTraceId = callRecording?.trace_id || callRecording?.call_data?.trace_id || null
  const resolvedProviderPlatform = useMemo(() => {
    const stored = (callRecording?.provider_platform || '').toLowerCase()
    if (stored && stored !== 'external') return stored
    const callData = callRecording?.call_data as Record<string, unknown> | undefined
    if (looksLikeRetellCallData(callData)) return 'retell'
    if (looksLikeVapiCallData(callData)) return 'vapi'
    return stored
  }, [callRecording?.provider_platform, callRecording?.call_data])
  const hasElevenLabsProviderTraceCandidate =
    resolvedProviderPlatform === 'elevenlabs' &&
    !!callRecording?.provider_call_id
  const liveTranscriptCount = Array.isArray(callRecording?.call_data?.live_transcript)
    ? callRecording.call_data.live_transcript.length
    : 0
  const isLiveIngestPlatform = ['pipecat', 'livekit', 'external'].includes(resolvedProviderPlatform)
  const hasSyntheticProviderTraceCandidate =
    ((resolvedProviderPlatform === 'vapi' || resolvedProviderPlatform === 'retell') &&
      !!callRecording?.provider_call_id) ||
    (isLiveIngestPlatform &&
      (liveTranscriptCount > 0 || !!linkedTraceId || !!callRecording?.call_data?.provider_trace))

  const {
    data: callTrace,
    isLoading: traceLoading,
    isError: traceError,
    error: traceFetchError,
    refetch: refetchTrace,
  } = useQuery<ObservabilityCallTrace>({
    queryKey: [
      'observability-call-trace',
      callShortId,
      linkedTraceId,
      resolvedProviderPlatform,
      callRecording?.updated_at,
    ],
    queryFn: () => apiClient.getObservabilityCallTrace(callShortId!),
    enabled:
      !!callShortId &&
      (!!linkedTraceId || hasElevenLabsProviderTraceCandidate || hasSyntheticProviderTraceCandidate),
    retry: false,
    refetchInterval: () => {
      const call = queryClient.getQueryData<ObservabilityCall>(['observability-call', callShortId])
      if (!call) return false
      const live = call.is_live || liveEvents.has((call.call_event || '').toLowerCase())
      return live ? 3000 : false
    },
  })

  useEffect(() => {
    if (!callShortId || !callRecording) return
    if (!linkedTraceId && !hasSyntheticProviderTraceCandidate && !hasElevenLabsProviderTraceCandidate) {
      return
    }
    void refetchTrace()
  }, [
    callShortId,
    callRecording?.updated_at,
    callRecording?.provider_platform,
    resolvedProviderPlatform,
    linkedTraceId,
    hasSyntheticProviderTraceCandidate,
    hasElevenLabsProviderTraceCandidate,
    refetchTrace,
  ])

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
    const isLive = callRecording.is_live || liveEvents.has((callRecording.call_event || '').toLowerCase())
    if (!isLive) return

    let eventSource: EventSource | null = null
    try {
      const url = apiClient.getObservabilityCallLiveEventsUrl(callShortId)
      eventSource = new EventSource(url)

      eventSource.onmessage = (event) => {
        try {
          const entry = JSON.parse(event.data)
          setLiveTranscript((prev) => [...prev, entry])
        } catch {
          // ignore malformed events
        }
      }
    } catch {
      // Polling via react-query still updates live_transcript from call_data
    }

    return () => {
      eventSource?.close()
    }
  }, [callShortId, callRecording?.call_event, callRecording?.is_live])

  const storageKey = callRecording?.call_data?.recording_s3_key ?? undefined
  const providerRecordingUrl = useMemo(() => {
    const callData = callRecording?.call_data
    if (!callData || typeof callData !== 'object') return null
    const artifact = (callData as any).artifact
    const candidate = [
      (callData as any).recording_url,
      (callData as any).recording_multi_channel_url,
      (callData as any).recordingUrl,
      (callData as any).stereoRecordingUrl,
      (callData as any).monoRecordingUrl,
      artifact?.recordingUrl,
      artifact?.stereoRecordingUrl,
      artifact?.monoRecordingUrl,
      artifact?.recording?.url,
      artifact?.recording?.stereoUrl,
      artifact?.recording?.monoUrl,
    ].find((value) => typeof value === 'string' && value.trim().length > 0)
    return typeof candidate === 'string' ? candidate : null
  }, [callRecording?.call_data])
  const hasStorageRecording = !!storageKey
  const hasRecordingCandidate = hasStorageRecording || !!providerRecordingUrl
  const isLiveCallActive =
    !!callRecording?.is_live || liveEvents.has((callRecording?.call_event || '').toLowerCase())

  const {
    data: archivedAudioBlobUrl,
    isLoading: archivedAudioLoading,
  } = useObservabilityCallAudioBlob(callShortId, !isLiveCallActive && hasRecordingCandidate)

  const {
    data: presignedRecording,
    isLoading: presignedLoading,
  } = useRecordingPresignedUrl(storageKey)

  const { data: evaluators = [] } = useQuery({
    queryKey: ['evaluators'],
    queryFn: () => apiClient.listEvaluators(),
    enabled: showEvalModal,
  })

  const deleteMutation = useMutation({
    mutationFn: () => apiClient.deleteObservabilityCall(callShortId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['observability-calls'] })
      navigate('/observability/calls')
    },
  })

  const evaluateMutation = useMutation({
    mutationFn: (evaluatorId: string) =>
      apiClient.evaluateObservabilityCall(callShortId!, evaluatorId),
    onSuccess: (data) => {
      setShowEvalModal(false)
      setSelectedEvaluator('')
      navigate(`/results/${data.result_id}`)
    },
  })

  const refreshMutation = useMutation({
    mutationFn: () => apiClient.refreshObservabilityCall(callShortId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['observability-call', callShortId] })
      queryClient.invalidateQueries({ queryKey: ['observability-call-trace', callShortId] })
    },
  })

  const callDataEarly = callRecording?.call_data
  const callStartMs = useMemo(() => {
    const started = callDataEarly?.startedAt || callDataEarly?.started_at
    if (!started) return null
    const ms = new Date(started).getTime()
    return Number.isNaN(ms) ? null : ms
  }, [callDataEarly?.startedAt, callDataEarly?.started_at])

  const traceSpans = useMemo(() => {
    if (!callTrace?.spans?.length) return []
    return flattenSpanTree(buildSpanTree(callTrace))
  }, [callTrace])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <Loader className="w-8 h-8 text-indigo-500 animate-spin mx-auto" />
          <p className="text-sm text-gray-500 mt-3">Loading call details...</p>
        </div>
      </div>
    )
  }

  if (!callRecording) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12">
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-6 text-center">
          <XCircle className="w-10 h-10 text-rose-400 mx-auto mb-3" />
          <p className="text-sm font-medium text-rose-800">Call not found</p>
          <Button
            onClick={() => navigate('/observability/calls')}
            variant="ghost"
            size="sm"
            className="mt-4"
          >
            <ArrowLeft className="w-4 h-4 mr-1.5" />
            Back to Calls
          </Button>
        </div>
      </div>
    )
  }

  const callData = callRecording.call_data
  const providerCallData = callData as any
  type TranscriptTurn = { role: 'user' | 'agent'; content: string; start_time?: number }
  const startedAtValue = callData?.startedAt || callData?.started_at
  const callStartMsFromData =
    startedAtValue && !Number.isNaN(new Date(startedAtValue).getTime())
      ? new Date(startedAtValue).getTime()
      : null
  const liveTranscriptEntries: Array<{
    role: string
    content: string
    timestamp?: string
    start_time?: number
  }> = Array.isArray(callData?.live_transcript) ? callData.live_transcript : []
  const extractTranscriptText = (value: unknown): string => {
    if (typeof value === 'string') return value.trim()
    if (typeof value === 'number' || typeof value === 'boolean') return String(value)
    if (Array.isArray(value)) {
      return value
        .map((entry) => extractTranscriptText(entry))
        .filter(Boolean)
        .join(' ')
        .trim()
    }
    if (value && typeof value === 'object') {
      const record = value as Record<string, unknown>
      const candidates = [record.text, record.content, record.message, record.transcript, record.value]
      for (const candidate of candidates) {
        const parsed = extractTranscriptText(candidate)
        if (parsed) return parsed
      }
    }
    return ''
  }
  const messagesFromLive = liveTranscriptEntries
    .map((entry) => ({
      role: entry.role === 'user' ? 'user' : 'assistant',
      content: extractTranscriptText(entry.content),
      start_time:
        typeof entry.start_time === 'number'
          ? entry.start_time
          : entry.timestamp
            ? new Date(entry.timestamp).getTime()
            : undefined,
    }))
    .filter((entry) => entry.content.length > 0)
  const normalizedCallDataMessages = Array.isArray(callData?.messages)
    ? callData.messages
        .map((entry: any) => ({
          role: String(entry?.role || '').toLowerCase(),
          content: extractTranscriptText(entry?.content ?? entry?.message ?? entry),
          start_time: (() => {
            const startCandidate = entry?.start_time ?? entry?.timestamp ?? entry?.time ?? entry?.secondsFromStart
            if (typeof startCandidate !== 'number') return undefined
            if (startCandidate > 1e10) return startCandidate
            if (startCandidate > 1e6 && callStartMsFromData != null) return startCandidate
            if (startCandidate < 1e6 && callStartMsFromData != null) return callStartMsFromData + startCandidate * 1000
            return startCandidate * 1000
          })(),
        }))
        .filter((entry: any) => entry.content.length > 0 && entry.role !== 'system')
    : []
  const messages: any[] | undefined = normalizedCallDataMessages.length > 0
    ? normalizedCallDataMessages
    : messagesFromLive.length > 0
      ? messagesFromLive
      : undefined

  const providerMessagesTurns = Array.isArray(providerCallData?.messages)
    ? providerCallData.messages
        .filter((entry: any) => {
          if (!entry || typeof entry !== 'object') return false
          const role = String(entry.role || '').toLowerCase()
          if (role === 'system') return false
          const content = extractTranscriptText(entry.content ?? entry.message ?? entry)
          return content.length > 0
        })
        .map((entry: any) => {
          const roleRaw = String(entry.role || '').toLowerCase()
          const role =
            roleRaw === 'user' || roleRaw === 'caller' || roleRaw === 'customer'
              ? 'user'
              : 'assistant'
          const startCandidate = entry.start_time ?? entry.timestamp ?? entry.time
          const startMs =
            typeof startCandidate === 'number'
              ? (startCandidate > 1e10 ? startCandidate : startCandidate * 1000)
              : undefined
          return {
            role,
            content: extractTranscriptText(entry.content ?? entry.message ?? entry),
            start_time: startMs,
          }
        })
    : []

  const artifactMessagesTurns =
    Array.isArray(providerCallData?.artifact?.messages)
      ? providerCallData.artifact.messages
          .filter((entry: any) => {
            if (!entry || typeof entry !== 'object') return false
            const role = String(entry.role || '').toLowerCase()
            if (role === 'system') return false
            const content = extractTranscriptText(entry.content ?? entry.message ?? entry)
            return content.length > 0
          })
          .map((entry: any) => {
            const roleRaw = String(entry.role || '').toLowerCase()
            const role =
              roleRaw === 'user' || roleRaw === 'caller' || roleRaw === 'customer'
                ? 'user'
                : 'assistant'
            const startCandidate = entry.start_time ?? entry.timestamp ?? entry.time
            const startMs =
              typeof startCandidate === 'number'
                ? (startCandidate > 1e10 ? startCandidate : startCandidate * 1000)
                : undefined
            return {
              role,
              content: extractTranscriptText(entry.content ?? entry.message ?? entry),
              start_time: startMs,
            }
          })
      : []

  const transcriptObjectTurns = Array.isArray(providerCallData?.transcript_object)
    ? providerCallData.transcript_object
        .filter((entry: any) => entry?.content || entry?.text)
        .map((entry: any) => {
          const roleRaw = String(entry.role || entry.speaker || '').toLowerCase()
          const role = roleRaw === 'user' ? 'user' : 'assistant'
          const startSecs = typeof entry.start === 'number' ? entry.start : null
          return {
            role,
            content: String(entry.content ?? entry.text ?? ''),
            start_time:
              startSecs !== null && callStartMsFromData !== null
                ? callStartMsFromData + startSecs * 1000
                : undefined,
          }
        })
    : []

  const rawTranscriptTurns = Array.isArray(providerCallData?.raw_data?.transcript)
    ? providerCallData.raw_data.transcript
        .filter((entry: any) => entry?.message)
        .map((entry: any) => {
          const role = String(entry.role || '').toLowerCase() === 'user' ? 'user' : 'assistant'
          const startSecs = typeof entry.time_in_call_secs === 'number' ? entry.time_in_call_secs : null
          return {
            role,
            content: String(entry.message),
            start_time:
              startSecs !== null && callStartMsFromData !== null
                ? callStartMsFromData + startSecs * 1000
                : undefined,
          }
        })
    : []

  const transcriptTextTurns =
    typeof providerCallData?.transcript === 'string' && providerCallData.transcript.trim()
      ? providerCallData.transcript
          .split('\n')
          .map((line: string) => line.trim())
          .filter(Boolean)
          .map((line: string) => {
            const lower = line.toLowerCase()
            const isUser = lower.startsWith('user:')
            const isAgent = lower.startsWith('agent:')
            if (isUser || isAgent) {
              return {
                role: isUser ? 'user' : 'assistant',
                content: line.split(':').slice(1).join(':').trim(),
              }
            }
            return { role: 'assistant', content: line }
          })
      : []

  const artifactTranscriptTurns =
    typeof providerCallData?.artifact?.transcript === 'string' && providerCallData.artifact.transcript.trim()
      ? providerCallData.artifact.transcript
          .split('\n')
          .map((line: string) => line.trim())
          .filter(Boolean)
          .map((line: string) => {
            const lower = line.toLowerCase()
            const isUser = lower.startsWith('user:')
            const isAgent = lower.startsWith('agent:')
            if (isUser || isAgent) {
              return {
                role: isUser ? 'user' : 'assistant',
                content: line.split(':').slice(1).join(':').trim(),
              }
            }
            return { role: 'assistant', content: line }
          })
      : []
  const playbackUrl = archivedAudioBlobUrl || presignedRecording?.url || providerRecordingUrl
  const audioLoading =
    (hasStorageRecording && presignedLoading && !playbackUrl) ||
    (hasRecordingCandidate && archivedAudioLoading && !playbackUrl)

  const isLiveCall = callRecording.is_live || liveEvents.has((callRecording.call_event || '').toLowerCase())

  const toTranscriptTurn = (
    entry: { role?: string; content?: unknown; start_time?: number } | null | undefined,
  ): TranscriptTurn | null => {
    if (!entry || typeof entry !== 'object') return null
    const content =
      typeof entry.content === 'string'
        ? entry.content.trim()
        : entry.content == null
          ? ''
          : String(entry.content).trim()
    if (!content) return null
    return {
      role: entry.role === 'user' ? 'user' : 'agent',
      content,
      start_time: typeof entry.start_time === 'number' ? entry.start_time : undefined,
    }
  }

  const persistedTurnsSource =
    messages && messages.length > 0
      ? messages
      : messagesFromLive.length > 0
        ? messagesFromLive
        : providerMessagesTurns.length > 0
          ? providerMessagesTurns
          : artifactMessagesTurns.length > 0
            ? artifactMessagesTurns
            : artifactTranscriptTurns.length > 0
              ? artifactTranscriptTurns
              : transcriptObjectTurns.length > 0
                ? transcriptObjectTurns
                : rawTranscriptTurns.length > 0
                  ? rawTranscriptTurns
                  : transcriptTextTurns

  const persistedTurns: TranscriptTurn[] = persistedTurnsSource
    .map(toTranscriptTurn)
    .filter((turn: TranscriptTurn | null): turn is TranscriptTurn => Boolean(turn))
  const liveTurns: TranscriptTurn[] = liveTranscript
    .filter((entry) => entry?.content)
    .map((entry) =>
      toTranscriptTurn({
        role: entry.role,
        content: entry.content,
        start_time:
          typeof entry.start_time === 'number'
            ? entry.start_time
            : entry.timestamp
              ? new Date(entry.timestamp).getTime()
              : undefined,
      }),
    )
    .filter((turn): turn is TranscriptTurn => Boolean(turn))

  const transcriptTurns: TranscriptTurn[] =
    isLiveCall && liveTurns.length > 0 ? liveTurns : persistedTurns
  const hasTranscript = transcriptTurns.length > 0

  const computeDuration = (): string | null => {
    const started = callData?.startedAt || callData?.started_at
    const ended = callData?.endedAt || callData?.ended_at
    if (started && ended) {
      const start = new Date(started).getTime()
      const end = new Date(ended).getTime()
      if (!isNaN(start) && !isNaN(end)) {
        const diffSec = Math.floor((end - start) / 1000)
        const mins = Math.floor(diffSec / 60)
        const secs = diffSec % 60
        return `${mins}m ${secs}s`
      }
    }
    if (typeof callData?.duration_seconds === 'number') {
      const diffSec = Math.floor(callData.duration_seconds)
      const mins = Math.floor(diffSec / 60)
      const secs = diffSec % 60
      return `${mins}m ${secs}s`
    }
    return null
  }

  const formatMessageTime = (timestamp: number): string => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  const duration = computeDuration()

  let durationSeconds: number | null = null
  if (typeof callData?.duration_seconds === 'number') {
    durationSeconds = callData.duration_seconds
  } else {
    const started = callData?.startedAt || callData?.started_at
    const ended = callData?.endedAt || callData?.ended_at
    if (started && ended) {
      const diff = (new Date(ended).getTime() - new Date(started).getTime()) / 1000
      if (!Number.isNaN(diff) && diff > 0) durationSeconds = diff
    }
  }

  const waveformSegments = buildWaveformSegments(callData, transcriptTurns, durationSeconds)

  const agentDisplayName = callRecording.agent?.name || 'Agent'
  const storedProviderTrace = callData?.provider_trace

  const hasTraceTab =
    !!linkedTraceId ||
    !!storedProviderTrace ||
    hasElevenLabsProviderTraceCandidate ||
    hasSyntheticProviderTraceCandidate ||
    (!!callTrace && callTrace.spans.length > 0)
  const hasTraceData =
    !!storedProviderTrace ||
    (!!callTrace && (callTrace.spans?.length ?? 0) > 0)
  const syntheticTraceSource = callTrace?.trace_source?.endsWith('_synthetic')
    ? callTrace.trace_source
    : null
  const providerTraceSource = typeof storedProviderTrace?.trace_source === 'string'
    ? storedProviderTrace.trace_source
    : typeof storedProviderTrace?.source === 'string'
      ? storedProviderTrace.source
      : null
  const hasArchivedTrace = storedProviderTrace?.storage === 's3'
  const hasRealProviderTrace = !!providerTraceSource && !providerTraceSource.endsWith('_synthetic')
  const showTabs =
    hasTranscript ||
    hasTraceTab ||
    isLiveCall ||
    (!isLiveCall && hasRecordingCandidate)
  const canRefreshProviderPayload = Boolean(
    callRecording.provider_call_id &&
      (callRecording.provider_platform || resolvedProviderPlatform !== 'external'),
  )
  const traceAvailabilityLabel = hasTraceData
    ? hasArchivedTrace
      ? 'Archived provider trace'
      : syntheticTraceSource || providerTraceSource?.endsWith('_synthetic')
        ? 'Synthetic provider trace'
        : hasRealProviderTrace
          ? 'Real provider trace'
          : 'Deep trace available'
    : hasSyntheticProviderTraceCandidate
      ? 'Synthetic trace on refresh'
      : callRecording.provider_platform
        ? 'Provider report only (Level 1)'
        : 'Trace unavailable'
  const traceAvailabilityTone = hasTraceData
    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
    : 'bg-amber-50 text-amber-700 border-amber-200'

  const handleTranscriptTurnClick = (index: number, role: 'user' | 'agent') => {
    setHighlightedTranscriptIndex(index)
    if (traceSpans.length === 0) return
    const userTurnIndex =
      role === 'user'
        ? transcriptTurns.slice(0, index + 1).filter((t: TranscriptTurn) => t.role === 'user').length - 1
        : Math.max(
            0,
            transcriptTurns.slice(0, index + 1).filter((t: TranscriptTurn) => t.role === 'user').length - 1,
          )
    const turnSpan = findTurnSpanForTranscriptIndex(userTurnIndex, traceSpans)
    if (turnSpan?.span_id) {
      setSelectedTraceSpanId(turnSpan.span_id)
      setActiveTab('trace')
    }
  }

  const traceErrorDisplay = traceFetchError
    ? getTraceFetchErrorDisplay(traceFetchError)
    : { title: '', body: '' }

  const tabClass = (tab: DetailTab) =>
    `px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
      activeTab === tab
        ? 'border-indigo-600 text-indigo-700'
        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-200'
    }`

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-6">
        <Button
          variant="outline"
          onClick={() => navigate('/observability/calls')}
          leftIcon={<ArrowLeft className="h-4 w-4" />}
          className="mb-4"
        >
          Back to Calls
        </Button>

        <div className="bg-white shadow rounded-lg p-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Call Details</h1>
              <p className="text-sm text-gray-500 mt-1">
                Call ID:{' '}
                <span className="font-mono font-semibold text-primary-600">
                  {callRecording.call_short_id}
                </span>
              </p>
            </div>
            <div className="flex items-center gap-3">
              {hasTranscript && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => setShowEvalModal(true)}
                  leftIcon={<Sparkles className="h-4 w-4" />}
                >
                  Run Evaluation
                </Button>
              )}
              {canRefreshProviderPayload && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => refreshMutation.mutate()}
                  isLoading={refreshMutation.isPending}
                  leftIcon={!refreshMutation.isPending ? <RotateCw className="h-4 w-4" /> : undefined}
                >
                  Refresh
                </Button>
              )}
              <Button
                variant="danger"
                size="sm"
                onClick={() => setShowDelete(true)}
                isLoading={deleteMutation.isPending}
                leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
              >
                Delete
              </Button>
              <EventBadge event={callRecording.call_event ?? undefined} />
            </div>
          </div>

          {/* Metadata grid */}
          <div className="mt-6 grid grid-cols-2 md:grid-cols-6 gap-4">
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Status</p>
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${
                  callRecording.status === 'updated'
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    : 'bg-yellow-50 text-yellow-700 border-yellow-200'
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    callRecording.status === 'updated' ? 'bg-emerald-500' : 'bg-yellow-500'
                  }`}
                />
                {callRecording.status === 'updated' ? 'Received' : callRecording.status}
              </span>
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Platform</p>
              <PlatformBadge platform={callRecording.provider_platform ?? undefined} />
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Agent</p>
              <CallAgentLink
                agent={callRecording.agent}
                callData={callData}
              />
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Observability</p>
              <div className="space-y-1">
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border ${traceAvailabilityTone}`}>
                  {traceAvailabilityLabel}
                </span>
                <div className="text-[11px] text-gray-500">
                  Transcript: <span className="font-medium text-gray-700">{transcriptTurns.length} turns</span>
                </div>
              </div>
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Provider Call ID</p>
              <p
                className="text-sm font-mono text-gray-900 text-xs truncate max-w-[180px]"
                title={callRecording.provider_call_id ?? undefined}
              >
                {callRecording.provider_call_id || 'N/A'}
              </p>
            </div>
            {linkedTraceId && (
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Trace ID</p>
                <p className="text-xs font-mono text-gray-900 truncate max-w-[220px]" title={linkedTraceId}>
                  {linkedTraceId}
                </p>
              </div>
            )}
            {duration && (
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Duration</p>
                <p className="text-sm text-gray-900 flex items-center">
                  <Clock className="w-4 h-4 mr-1" />
                  {duration}
                </p>
              </div>
            )}
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Created</p>
              <p className="text-sm text-gray-900">
                {callRecording.created_at
                  ? new Date(callRecording.created_at).toLocaleString()
                  : 'N/A'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {showTabs && (
        <div className="mb-4 border-b border-gray-200 bg-white rounded-t-lg shadow-sm">
          <nav className="flex gap-1 px-2" aria-label="Call detail sections">
            <button type="button" className={tabClass('overview')} onClick={() => setActiveTab('overview')}>
              Overview
            </button>
            {(hasTranscript || isLiveCall) && (
              <button type="button" className={tabClass('transcript')} onClick={() => setActiveTab('transcript')}>
                Transcript
                <span className="ml-1.5 text-xs text-gray-400">({transcriptTurns.length})</span>
              </button>
            )}
            {(hasTraceTab || isLiveCall || (!isLiveCall && hasRecordingCandidate)) && (
              <button type="button" className={tabClass('trace')} onClick={() => setActiveTab('trace')}>
                Trace &amp; Recording
              </button>
            )}
          </nav>
        </div>
      )}

      {(!showTabs || activeTab === 'overview') && (
        <>
          {callData && (
            <ProviderInsightsPanel
              platform={callRecording.provider_platform ?? undefined}
              callData={callData}
            />
          )}

          <CallSummaryPanel callData={callData} duration={duration} />
        </>
      )}

      {showTabs && activeTab === 'transcript' && (hasTranscript || isLiveCall) && (
        <div className="mb-6 bg-white shadow rounded-lg p-6">
          <div className="rounded-xl border border-gray-100 bg-gray-50/30 flex flex-col min-h-[560px]">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
              <div className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4 text-indigo-500" />
                <span className="text-sm font-medium text-gray-900">
                  {isLiveCall ? 'Live Transcript' : 'Transcript'}
                </span>
                {isLiveCall && (
                  <span className="px-2 py-0.5 text-xs bg-sky-100 text-sky-800 rounded-full animate-pulse">Live</span>
                )}
                <span className="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full">
                  {transcriptTurns.length} turns
                </span>
              </div>
              <div className="flex items-center gap-3">
                {traceSpans.length > 0 && (
                  <p className="text-[11px] text-gray-500 hidden sm:block">Click a message to open trace</p>
                )}
                {!isLiveCall && audioLoading && (
                  <Loader className="w-4 h-4 animate-spin text-gray-400" />
                )}
                {!isLiveCall && playbackUrl && (
                  <>
                    <audio controls src={playbackUrl} preload="metadata" className="h-8 w-48 sm:w-64" />
                    <a
                      href={playbackUrl}
                      download={`call_${callRecording.call_short_id}.wav`}
                      className="p-1.5 text-gray-400 hover:text-indigo-600 rounded-lg transition-colors"
                      title="Download recording"
                    >
                      <Download className="h-4 w-4" />
                    </a>
                  </>
                )}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {transcriptTurns.length === 0 ? (
                <p className="text-sm text-gray-500 text-center py-8">Waiting for speech…</p>
              ) : (
                transcriptTurns.map((turn, index) => {
                  const isUser = turn.role === 'user'
                  const isLinked = highlightedTranscriptIndex === index
                  const canLink = traceSpans.length > 0

                  return (
                    <motion.div
                      key={index}
                      className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.2, delay: index * 0.03 }}
                    >
                      <button
                        type="button"
                        disabled={!canLink}
                        onClick={() => handleTranscriptTurnClick(index, turn.role)}
                        className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-left transition-shadow ${
                          isUser
                            ? 'bg-indigo-600 text-white rounded-br-sm'
                            : 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm'
                        } ${canLink ? 'hover:ring-2 hover:ring-indigo-300 cursor-pointer' : 'cursor-default'} ${
                          isLinked ? 'ring-2 ring-violet-400 shadow-md' : ''
                        }`}
                      >
                        <div
                          className={`flex items-center gap-2 mb-0.5 ${
                            isUser ? 'text-indigo-200' : 'text-gray-400'
                          }`}
                        >
                          <span className="text-[10px] font-semibold uppercase tracking-wider">
                            {isUser ? 'Caller' : agentDisplayName}
                          </span>
                          {turn.start_time && (
                            <span className="text-[10px] tabular-nums">
                              {formatMessageTime(turn.start_time)}
                            </span>
                          )}
                        </div>
                        <p className="text-sm leading-relaxed">{turn.content}</p>
                      </button>
                    </motion.div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      )}

      {showTabs && activeTab === 'trace' && (
        <div className="mb-6 bg-white shadow rounded-lg p-6">
          {hasTraceTab ? (
            <TraceRecordingPanel
              callShortId={callRecording.call_short_id}
              traceId={linkedTraceId}
              callTrace={callTrace}
              traceLoading={traceLoading}
              traceError={traceError}
              traceErrorDisplay={traceErrorDisplay}
              playbackUrl={!isLiveCall ? playbackUrl : null}
              audioLoading={audioLoading}
              isLiveCall={isLiveCall}
              callStartMs={callStartMs}
              waveformSegments={waveformSegments}
              agentLabel={agentDisplayName}
              hasStorageRecording={hasRecordingCandidate}
              fallbackDurationSec={durationSeconds}
              onRefreshTrace={() => refetchTrace()}
              selectedSpanId={selectedTraceSpanId}
              onSelectedSpanIdChange={setSelectedTraceSpanId}
            />
          ) : (
            <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-700">
              Trace is not available for this call yet.
            </div>
          )}
        </div>
      )}

      {!showTabs && (
        <div className="mb-6 bg-white shadow rounded-lg p-6">
          <TraceRecordingPanel
            callShortId={callRecording.call_short_id}
            traceId={linkedTraceId}
            callTrace={callTrace}
            traceLoading={traceLoading}
            traceError={traceError}
            traceErrorDisplay={traceErrorDisplay}
            playbackUrl={!isLiveCall ? playbackUrl : null}
            audioLoading={audioLoading}
            isLiveCall={isLiveCall}
            callStartMs={callStartMs}
            waveformSegments={waveformSegments}
            agentLabel={agentDisplayName}
            hasStorageRecording={hasRecordingCandidate}
            fallbackDurationSec={durationSeconds}
            onRefreshTrace={() => refetchTrace()}
            selectedSpanId={selectedTraceSpanId}
            onSelectedSpanIdChange={setSelectedTraceSpanId}
          />
        </div>
      )}

      <ConfirmModal
        title="Delete call"
        description="This will permanently remove this call record."
        isOpen={showDelete}
        isLoading={deleteMutation.isPending}
        onCancel={() => setShowDelete(false)}
        onConfirm={() => deleteMutation.mutate()}
      />

      {/* Evaluate Modal */}
      <AnimatePresence>
        {showEvalModal && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div
              className="absolute inset-0 bg-gray-500 bg-opacity-75"
              onClick={() => {
                setShowEvalModal(false)
                setSelectedEvaluator('')
              }}
            />
            <motion.div
              className="relative bg-white rounded-2xl shadow-2xl max-w-lg w-full mx-4 overflow-hidden"
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              transition={{ duration: 0.2 }}
            >
              <div className="px-6 py-5 border-b border-gray-100">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900">Run Evaluation</h2>
                    <p className="text-sm text-gray-500 mt-0.5">
                      Evaluate call <span className="font-mono font-semibold">{callRecording.call_short_id}</span> against an evaluator
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      setShowEvalModal(false)
                      setSelectedEvaluator('')
                    }}
                    className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Select Evaluator
                  </label>
                  <select
                    value={selectedEvaluator}
                    onChange={(e) => setSelectedEvaluator(e.target.value)}
                    className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 bg-white"
                  >
                    <option value="">Choose an evaluator...</option>
                    {evaluators.map((evaluator: any) => (
                      <option key={evaluator.id} value={evaluator.id}>
                        {evaluator.evaluator_id} &mdash;{' '}
                        {evaluator.custom_prompt
                          ? `Custom: ${evaluator.name || 'Unnamed'}`
                          : `Agent: ${evaluator.agent_id?.substring(0, 8) || '?'}...`}
                      </option>
                    ))}
                  </select>
                </div>

                {evaluateMutation.isError && (
                  <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-sm text-rose-700">
                    {(evaluateMutation.error as any)?.response?.data?.detail || 'Failed to start evaluation'}
                  </div>
                )}
              </div>

              <div className="px-6 py-4 border-t border-gray-100 bg-gray-50/50 flex justify-end gap-3">
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
                  {evaluateMutation.isPending ? 'Starting...' : 'Run Evaluation'}
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function CallSummaryPanel({
  callData,
  duration,
}: {
  callData: ObservabilityCall['call_data']
  duration: string | null
}) {
  if (!callData && !duration) return null

  return (
    <div className="mb-6">
      <div className="rounded-xl border border-gray-100 bg-white shadow p-5 max-w-lg">
        <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Phone className="h-4 w-4 text-indigo-500" />
          Call Summary
        </h3>
        <div className="space-y-3">
          {duration && (
            <div className="p-3 bg-gray-50 rounded-lg border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">Duration</p>
              <p className="text-base font-semibold text-gray-900 tabular-nums">{duration}</p>
            </div>
          )}
          {callData?.startedAt && (
            <div className="p-3 bg-gray-50 rounded-lg border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">Started At</p>
              <p className="text-sm text-gray-900">{new Date(callData.startedAt).toLocaleString()}</p>
            </div>
          )}
          {callData?.endedAt && (
            <div className="p-3 bg-gray-50 rounded-lg border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">Ended At</p>
              <p className="text-sm text-gray-900">{new Date(callData.endedAt).toLocaleString()}</p>
            </div>
          )}
          {(callData?.from_phone_number || callData?.to_phone_number) && (
            <div className="p-3 bg-gray-50 rounded-lg border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">Phone Numbers</p>
              <div className="space-y-2 mt-1.5">
                {callData.from_phone_number && (
                  <div className="flex items-center gap-2">
                    <PhoneOutgoing className="w-3.5 h-3.5 text-gray-400" />
                    <span className="text-sm text-gray-700 font-mono">{callData.from_phone_number}</span>
                  </div>
                )}
                {callData.to_phone_number && (
                  <div className="flex items-center gap-2">
                    <PhoneIncoming className="w-3.5 h-3.5 text-gray-400" />
                    <span className="text-sm text-gray-700 font-mono">{callData.to_phone_number}</span>
                  </div>
                )}
              </div>
            </div>
          )}
          {callData?.endedReason && (
            <div className="p-3 bg-gray-50 rounded-lg border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">End Reason</p>
              <EndReasonBadge reason={callData.endedReason} />
            </div>
          )}
          {callData?.metadata && typeof callData.metadata === 'object' && !Array.isArray(callData.metadata) && Object.keys(callData.metadata).length > 0 && (
            <div className="p-3 bg-gray-50 rounded-lg border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-2">Metadata</p>
              <div className="space-y-1.5">
                {Object.entries(callData.metadata as Record<string, unknown>).map(([key, value]) => (
                  <div key={key} className="flex items-start gap-2">
                    <Tag className="w-3 h-3 text-gray-300 mt-0.5 flex-shrink-0" />
                    <div className="min-w-0">
                      <span className="text-xs text-gray-500">{key}:</span>
                      <span className="text-xs text-gray-800 ml-1 font-medium">{String(value)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

type InsightItem = { label: string; value: string }
type ChartDatum = { name: string; value: number }

function ProviderInsightsPanel({
  platform,
  callData,
}: {
  platform?: string
  callData: ObservabilityCall['call_data']
}) {
  const normalizedPlatform = String(platform || '').toLowerCase()
  const providerLabel = normalizedPlatform ? getIntegrationPlatformLabel(normalizedPlatform as IntegrationPlatform) : 'Provider'
  const raw = (callData || {}) as Record<string, any>
  const chartColors = ['#4f46e5', '#06b6d4', '#f59e0b', '#10b981', '#f97316', '#a855f7']

  const formatValue = (value: unknown): string => {
    if (value == null) return 'N/A'
    if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : 'N/A'
    if (typeof value === 'boolean') return value ? 'Yes' : 'No'
    const text = String(value).trim()
    return text.length > 0 ? text : 'N/A'
  }

  const formatCurrency = (value: unknown, digits = 4): string => {
    if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/A'
    return `$${value.toFixed(digits)}`
  }

  const toNumberOrNull = (value: unknown): number | null => {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null
    return value
  }

  const pushIfPresent = (items: InsightItem[], label: string, value: unknown) => {
    if (value == null) return
    if (typeof value === 'string' && value.trim().length === 0) return
    items.push({ label, value: formatValue(value) })
  }

  const addChartPoint = (data: ChartDatum[], name: string, value: unknown) => {
    const numericValue = toNumberOrNull(value)
    if (numericValue == null) return
    data.push({ name, value: numericValue })
  }

  const sections: Array<{ title: string; items: InsightItem[] }> = []
  const isElevenLabs = normalizedPlatform === 'elevenlabs'
  const isRetell = normalizedPlatform === 'retell'
  const elevenlabsMetadata = raw.raw_data?.metadata ?? raw.metadata
  const elevenlabsCharging = elevenlabsMetadata?.charging
  const elevenlabsRawTranscript = Array.isArray(raw.raw_data?.transcript)
    ? raw.raw_data.transcript
    : Array.isArray(raw.transcript) && raw.transcript.some((entry: unknown) => entry && typeof entry === 'object')
      ? raw.transcript
      : []
  const elevenlabsTokenTotals = {
    prompt: 0,
    completion: 0,
    cached: 0,
  }
  if (isElevenLabs) {
    const usageCandidates = [
      elevenlabsCharging?.llm_usage?.irreversible_generation,
      elevenlabsCharging?.llm_usage?.initiated_generation,
    ]
    usageCandidates.forEach((usage: any) => {
      const modelUsage = usage?.model_usage
      if (!modelUsage || typeof modelUsage !== 'object') return
      Object.values(modelUsage as Record<string, any>).forEach((model: any) => {
        elevenlabsTokenTotals.prompt += toNumberOrNull(model?.input?.tokens) ?? 0
        elevenlabsTokenTotals.cached += toNumberOrNull(model?.input_cache_read?.tokens) ?? 0
        elevenlabsTokenTotals.completion += toNumberOrNull(model?.output_total?.tokens) ?? 0
      })
    })
  }

  const summaryItems: InsightItem[] = []
  pushIfPresent(summaryItems, 'Summary', raw.analysis?.summary ?? raw.call_analysis?.call_summary ?? raw.summary)
  pushIfPresent(
    summaryItems,
    'Success Evaluation',
    raw.analysis?.success_evaluation ?? raw.analysis?.successEvaluation ?? raw.call_analysis?.call_successful,
  )
  pushIfPresent(summaryItems, 'User Sentiment', raw.call_analysis?.user_sentiment)
  pushIfPresent(summaryItems, 'Ended Reason', raw.ended_reason ?? raw.endedReason ?? raw.disconnection_reason ?? raw.reason)
  pushIfPresent(summaryItems, 'Call Type', raw.call_type ?? raw.type)
  if (summaryItems.length > 0) sections.push({ title: 'Call Analysis', items: summaryItems })

  const tokenItems: InsightItem[] = []
  const costBreakdown = raw.cost_breakdown || raw.costBreakdown || {}
  const promptTokensValue =
    costBreakdown.llm_prompt_tokens ??
    costBreakdown.llmPromptTokens ??
    (elevenlabsTokenTotals.prompt > 0 ? elevenlabsTokenTotals.prompt : undefined)
  const completionTokensValue =
    costBreakdown.llm_completion_tokens ??
    costBreakdown.llmCompletionTokens ??
    (elevenlabsTokenTotals.completion > 0 ? elevenlabsTokenTotals.completion : undefined)
  const cachedTokensValue =
    costBreakdown.llm_cached_prompt_tokens ??
    costBreakdown.llmCachedPromptTokens ??
    (elevenlabsTokenTotals.cached > 0 ? elevenlabsTokenTotals.cached : undefined)
  pushIfPresent(tokenItems, 'LLM Prompt Tokens', promptTokensValue)
  pushIfPresent(tokenItems, 'LLM Completion Tokens', completionTokensValue)
  pushIfPresent(
    tokenItems,
    'LLM Cached Prompt Tokens',
    cachedTokensValue,
  )
  pushIfPresent(tokenItems, 'TTS Characters', costBreakdown.tts_characters ?? costBreakdown.ttsCharacters)
  if (tokenItems.length > 0) sections.push({ title: 'Token & Usage', items: tokenItems })
  const tokenChartData: ChartDatum[] = []
  addChartPoint(tokenChartData, 'Prompt', promptTokensValue)
  addChartPoint(tokenChartData, 'Completion', completionTokensValue)
  addChartPoint(tokenChartData, 'Cached', cachedTokensValue)
  addChartPoint(tokenChartData, 'TTS Chars', costBreakdown.tts_characters ?? costBreakdown.ttsCharacters)

  const costItems: InsightItem[] = []
  const elevenlabsCreditsValue =
    toNumberOrNull(raw.cost) ??
    toNumberOrNull(elevenlabsMetadata?.cost) ??
    (() => {
      const callCharge = toNumberOrNull(elevenlabsCharging?.call_charge) ?? 0
      const llmCharge = toNumberOrNull(elevenlabsCharging?.llm_charge) ?? 0
      const platformCharge = toNumberOrNull(elevenlabsCharging?.platform_charge) ?? 0
      const total = callCharge + llmCharge + platformCharge
      return total > 0 ? total : null
    })()
  if (isElevenLabs) {
    pushIfPresent(
      costItems,
      'Total Cost (Credits)',
      elevenlabsCreditsValue != null ? `${elevenlabsCreditsValue.toLocaleString()} credits` : undefined,
    )
  } else {
    pushIfPresent(costItems, 'Total Cost', formatCurrency(raw.cost ?? raw.call_cost?.combined_cost ?? costBreakdown.total))
  }
  pushIfPresent(costItems, 'Transport Cost', formatCurrency(costBreakdown.transport))
  pushIfPresent(costItems, 'STT Cost', formatCurrency(costBreakdown.stt))
  pushIfPresent(costItems, 'LLM Cost', formatCurrency(costBreakdown.llm))
  pushIfPresent(costItems, 'TTS Cost', formatCurrency(costBreakdown.tts))
  pushIfPresent(costItems, 'Provider Fee', formatCurrency(costBreakdown.vapi))
  if (isElevenLabs) {
    pushIfPresent(
      costItems,
      'Call (TTS + Infra)',
      elevenlabsCharging?.call_charge != null ? `${Number(elevenlabsCharging.call_charge).toLocaleString()} credits` : undefined,
    )
    pushIfPresent(
      costItems,
      'LLM',
      elevenlabsCharging?.llm_charge != null ? `${Number(elevenlabsCharging.llm_charge).toLocaleString()} credits` : undefined,
    )
    pushIfPresent(
      costItems,
      'Platform',
      elevenlabsCharging?.platform_charge != null
        ? `${Number(elevenlabsCharging.platform_charge).toLocaleString()} credits`
        : undefined,
    )
    pushIfPresent(costItems, 'LLM Unit Price (USD)', formatCurrency(elevenlabsCharging?.llm_price, 6))
  }
  if (Array.isArray(raw.call_cost?.product_costs)) {
    raw.call_cost.product_costs.forEach((entry: any) => {
      if (!entry || typeof entry !== 'object') return
      pushIfPresent(costItems, `${formatValue(entry.product)} Cost`, formatCurrency(entry.cost, 3))
      pushIfPresent(costItems, `${formatValue(entry.product)} Unit Price`, formatCurrency(entry.unit_price, 6))
    })
  }
  if (costItems.length > 0) sections.push({ title: 'Costs', items: costItems })

  const formatElevenLabsCategoryLabel = (category: string): string =>
    category
      .split('_')
      .map((part) => (part ? part[0].toUpperCase() + part.slice(1) : part))
      .join(' ')

  const buildElevenLabsCostChartData = (): ChartDatum[] => {
    const data: ChartDatum[] = []
    const categoryUsage = elevenlabsCharging?.platform_usage?.category_usage
    if (categoryUsage && typeof categoryUsage === 'object') {
      Object.entries(categoryUsage as Record<string, any>).forEach(([category, usage]) => {
        addChartPoint(data, formatElevenLabsCategoryLabel(category), usage?.credits)
      })
    }

    const llmCharge = toNumberOrNull(elevenlabsCharging?.llm_charge)
    const callCharge = toNumberOrNull(elevenlabsCharging?.call_charge)
    const platformCharge = toNumberOrNull(elevenlabsCharging?.platform_charge)

    if (data.length === 0) {
      addChartPoint(data, 'Call (TTS + Infra)', callCharge)
      addChartPoint(data, 'LLM', llmCharge)
      addChartPoint(data, 'Platform', platformCharge)
    } else if (llmCharge != null && llmCharge > 0) {
      addChartPoint(data, 'LLM', llmCharge)
    }

    if (data.length > 0 && elevenlabsCreditsValue != null) {
      const segmentTotal = data.reduce((sum, entry) => sum + entry.value, 0)
      const remainder = elevenlabsCreditsValue - segmentTotal
      if (remainder > 0) addChartPoint(data, 'Other', remainder)
    }

    if (data.length === 0 && elevenlabsCreditsValue != null) {
      addChartPoint(data, 'Total Credits', elevenlabsCreditsValue)
    }

    return data
  }

  const costChartData: ChartDatum[] = []
  if (isElevenLabs) {
    costChartData.push(...buildElevenLabsCostChartData())
  } else {
    addChartPoint(costChartData, 'Transport', costBreakdown.transport)
    addChartPoint(costChartData, 'STT', costBreakdown.stt)
    addChartPoint(costChartData, 'LLM', costBreakdown.llm)
    addChartPoint(costChartData, 'TTS', costBreakdown.tts)
    addChartPoint(costChartData, 'Provider', costBreakdown.vapi)
    if (Array.isArray(raw.call_cost?.product_costs)) {
      raw.call_cost.product_costs.forEach((entry: any) => {
        if (!entry || typeof entry !== 'object') return
        addChartPoint(costChartData, formatValue(entry.product), entry.cost)
      })
    }
  }

  const formatCostChartValue = (value: number) =>
    isElevenLabs ? `${value.toLocaleString()} credits` : `$${value.toFixed(4)}`

  const latencyItems: InsightItem[] = []
  const latencyStats = raw.analysis?.latency_stats || raw.artifact?.performanceMetrics || {}
  pushIfPresent(latencyItems, 'Model Latency Avg (ms)', latencyStats.model_latency_avg ?? latencyStats.modelLatencyAverage)
  pushIfPresent(latencyItems, 'Voice Latency Avg (ms)', latencyStats.voice_latency_avg ?? latencyStats.voiceLatencyAverage)
  pushIfPresent(
    latencyItems,
    'Transcriber Latency Avg (ms)',
    latencyStats.transcriber_latency_avg ?? latencyStats.transcriberLatencyAverage,
  )
  pushIfPresent(
    latencyItems,
    'Endpointing Latency Avg (ms)',
    latencyStats.endpointing_latency_avg ?? latencyStats.endpointingLatencyAverage,
  )
  pushIfPresent(latencyItems, 'Turn Latency Avg (ms)', latencyStats.turn_latency_avg ?? latencyStats.turnLatencyAverage)
  pushIfPresent(latencyItems, 'P50 (ms)', latencyStats.p50)
  pushIfPresent(latencyItems, 'P90 (ms)', latencyStats.p90)
  pushIfPresent(latencyItems, 'P95 (ms)', latencyStats.p95)
  pushIfPresent(latencyItems, 'P99 (ms)', latencyStats.p99)

  const retellLatency = raw.latency || {}
  ;['e2e', 'asr', 'llm', 'tts'].forEach((key) => {
    const stats = retellLatency[key]
    if (!stats || typeof stats !== 'object') return
    pushIfPresent(latencyItems, `${key.toUpperCase()} P50 (ms)`, stats.p50)
    pushIfPresent(latencyItems, `${key.toUpperCase()} P90 (ms)`, stats.p90)
    pushIfPresent(latencyItems, `${key.toUpperCase()} Max (ms)`, stats.max)
  })
  if (isElevenLabs && latencyItems.length === 0) {
    const asrSamples: number[] = []
    const llmSamples: number[] = []
    const ttsSamples: number[] = []
    elevenlabsRawTranscript.forEach((entry: any) => {
      const metrics = entry?.conversation_turn_metrics?.metrics
      if (!metrics || typeof metrics !== 'object') return
      const pickMetricMs = (keys: string[]) => {
        for (const key of keys) {
          const elapsed = toNumberOrNull(metrics?.[key]?.elapsed_time)
          if (elapsed != null) return elapsed * 1000
        }
        return null
      }
      const asrMs = pickMetricMs(['convai_turn_asr_latency', 'convai_asr_trailing_service_latency'])
      const llmMs = pickMetricMs([
        'convai_llm_service_tt_last_sentence',
        'convai_llm_service_ttf_sentence',
        'convai_llm_service_ttfb',
      ])
      const ttsMs = pickMetricMs(['convai_tts_service_ttfb'])
      if (asrMs != null) asrSamples.push(asrMs)
      if (llmMs != null) llmSamples.push(llmMs)
      if (ttsMs != null) ttsSamples.push(ttsMs)
    })
    const avg = (arr: number[]) => (arr.length ? arr.reduce((acc, n) => acc + n, 0) / arr.length : null)
    const avgAsr = avg(asrSamples)
    const avgLlm = avg(llmSamples)
    const avgTts = avg(ttsSamples)
    pushIfPresent(latencyItems, 'ASR Latency Avg (ms)', avgAsr != null ? Math.round(avgAsr) : undefined)
    pushIfPresent(latencyItems, 'LLM Latency Avg (ms)', avgLlm != null ? Math.round(avgLlm) : undefined)
    pushIfPresent(latencyItems, 'TTS Latency Avg (ms)', avgTts != null ? Math.round(avgTts) : undefined)
    const turnAvg =
      avgAsr != null || avgLlm != null || avgTts != null
        ? Math.round((avgAsr ?? 0) + (avgLlm ?? 0) + (avgTts ?? 0))
        : null
    pushIfPresent(latencyItems, 'Turn Latency Avg (ms)', turnAvg ?? undefined)
  }
  if (latencyItems.length > 0) sections.push({ title: 'Latency', items: latencyItems })
  const latencyChartData: ChartDatum[] = []
  addChartPoint(latencyChartData, 'Model', latencyStats.model_latency_avg ?? latencyStats.modelLatencyAverage)
  addChartPoint(latencyChartData, 'Voice', latencyStats.voice_latency_avg ?? latencyStats.voiceLatencyAverage)
  addChartPoint(
    latencyChartData,
    'Transcriber',
    latencyStats.transcriber_latency_avg ?? latencyStats.transcriberLatencyAverage,
  )
  addChartPoint(
    latencyChartData,
    'Endpointing',
    latencyStats.endpointing_latency_avg ?? latencyStats.endpointingLatencyAverage,
  )
  addChartPoint(latencyChartData, 'Turn', latencyStats.turn_latency_avg ?? latencyStats.turnLatencyAverage)
  ;['e2e', 'asr', 'llm', 'tts'].forEach((key) => {
    const stats = retellLatency[key]
    if (!stats || typeof stats !== 'object') return
    addChartPoint(latencyChartData, `${key.toUpperCase()} P50`, stats.p50)
  })
  if (isElevenLabs && latencyChartData.length === 0 && latencyItems.length > 0) {
    const latencyByLabel: Record<string, string> = {
      'ASR Latency Avg (ms)': 'ASR',
      'LLM Latency Avg (ms)': 'LLM',
      'TTS Latency Avg (ms)': 'TTS',
      'Turn Latency Avg (ms)': 'Turn',
    }
    latencyItems.forEach((item) => {
      const label = latencyByLabel[item.label]
      if (!label) return
      const numeric = Number(item.value.replace(/[^0-9.]/g, ''))
      if (!Number.isNaN(numeric)) addChartPoint(latencyChartData, label, numeric)
    })
  }

  const systemItems: InsightItem[] = []
  pushIfPresent(systemItems, 'Provider Call ID', raw.call_id ?? raw.id)
  pushIfPresent(systemItems, 'Assistant ID', raw.assistant_id ?? raw.assistantId ?? raw.agent_id)
  pushIfPresent(systemItems, 'Status', raw.call_status ?? raw.status)
  pushIfPresent(systemItems, 'Start Time', raw.start_timestamp ?? raw.startedAt)
  pushIfPresent(systemItems, 'End Time', raw.end_timestamp ?? raw.endedAt)
  pushIfPresent(systemItems, 'Duration (seconds)', raw.duration_seconds ?? raw.call_cost?.total_duration_seconds ?? (typeof raw.duration_ms === 'number' ? Math.round(raw.duration_ms / 1000) : undefined))
  if (systemItems.length > 0) sections.push({ title: 'System Details', items: systemItems })

  const metaItems: InsightItem[] = []
  const metadata = raw.metadata
  if (metadata && typeof metadata === 'object' && !Array.isArray(metadata)) {
    Object.entries(metadata).forEach(([key, value]) => {
      metaItems.push({ label: key, value: formatValue(value) })
    })
  }
  if (metaItems.length > 0) sections.push({ title: 'Metadata', items: metaItems })

  const totalCostValue = isElevenLabs
    ? elevenlabsCreditsValue
    : isRetell
      ? (toNumberOrNull(raw.call_cost?.combined_cost) ?? toNumberOrNull(raw.cost) ?? toNumberOrNull(costBreakdown.total))
      : (toNumberOrNull(raw.cost) ?? toNumberOrNull(costBreakdown.total))
  const promptTokens = toNumberOrNull(promptTokensValue) ?? 0
  const completionTokens = toNumberOrNull(completionTokensValue) ?? 0
  const cachedTokens = toNumberOrNull(cachedTokensValue) ?? 0
  const totalTokens = promptTokens + completionTokens + cachedTokens
  const parseLatencyItem = (label: string): number | null => {
    const item = latencyItems.find((entry) => entry.label === label)
    if (!item) return null
    const numeric = Number(item.value.replace(/[^0-9.]/g, ''))
    return Number.isNaN(numeric) ? null : numeric
  }
  const derivedTurnLatency =
    parseLatencyItem('Turn Latency Avg (ms)') ??
    parseLatencyItem('P50 (ms)') ??
    (() => {
      const values = ['ASR Latency Avg (ms)', 'LLM Latency Avg (ms)', 'TTS Latency Avg (ms)']
        .map(parseLatencyItem)
        .filter((v): v is number => v != null)
      if (values.length === 0) return null
      return values.reduce((acc, value) => acc + value, 0)
    })()
  const turnLatency =
    toNumberOrNull(latencyStats.turn_latency_avg ?? latencyStats.turnLatencyAverage) ??
    toNumberOrNull(latencyStats.p50) ??
    (isRetell ? toNumberOrNull(retellLatency.e2e?.p50) : null) ??
    derivedTurnLatency
  const metricSectionTitles = new Set(['Token & Usage', 'Costs', 'Latency'])
  const coreSections = sections.filter((section) => !metricSectionTitles.has(section.title))
  const metricSections = sections.filter((section) => metricSectionTitles.has(section.title))

  if (sections.length === 0) return null

  return (
    <div className="mb-6 bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold text-gray-900 flex items-center mb-4">
        <Phone className="w-5 h-5 mr-2" />
        Provider Insights
        <span className="ml-2 px-2 py-0.5 text-xs bg-gray-100 text-gray-700 rounded-full">
          {providerLabel}
        </span>
      </h2>

      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="rounded-xl border border-indigo-100 bg-indigo-50/40 p-4">
            <p className="text-[10px] uppercase tracking-wider text-indigo-500 font-semibold mb-1">
              {isElevenLabs ? 'Total Cost (Credits)' : 'Total Cost'}
            </p>
            <p className="text-2xl font-bold text-indigo-800">
              {totalCostValue == null
                ? 'N/A'
                : isElevenLabs
                  ? `${totalCostValue.toLocaleString()} credits`
                  : `$${totalCostValue.toFixed(4)}`}
            </p>
          </div>
          <div className="rounded-xl border border-cyan-100 bg-cyan-50/40 p-4">
            <p className="text-[10px] uppercase tracking-wider text-cyan-600 font-semibold mb-1">Total LLM Tokens</p>
            <p className="text-2xl font-bold text-cyan-800">
              {isRetell && totalTokens === 0
                ? 'Not reported'
                : totalTokens > 0
                  ? totalTokens.toLocaleString()
                  : 'N/A'}
            </p>
          </div>
          <div className="rounded-xl border border-emerald-100 bg-emerald-50/40 p-4">
            <p className="text-[10px] uppercase tracking-wider text-emerald-600 font-semibold mb-1">Turn Latency</p>
            <p className="text-2xl font-bold text-emerald-800">{turnLatency == null ? 'N/A' : `${Math.round(turnLatency).toLocaleString()} ms`}</p>
          </div>
        </div>

        {(costChartData.length > 0 || tokenChartData.length > 0 || latencyChartData.length > 0) && (
          <div className="rounded-xl border border-gray-100 bg-gray-50/40 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Dashboards</h3>
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
              {costChartData.length > 0 && (
                <div className="rounded-lg bg-white border border-gray-100 p-3">
                  <p className="text-xs font-semibold text-gray-700 mb-2">
                    {isElevenLabs ? 'Credits Distribution' : 'Cost Distribution'}
                  </p>
                  <div className="h-52">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={costChartData}
                          dataKey="value"
                          nameKey="name"
                          cx="50%"
                          cy="50%"
                          outerRadius={72}
                          paddingAngle={isElevenLabs && costChartData.length > 1 ? 2 : 0}
                        >
                          {costChartData.map((_entry, index) => (
                            <Cell key={`cost-${index}`} fill={chartColors[index % chartColors.length]} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(value: number) => formatCostChartValue(value)} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {tokenChartData.length > 0 && (
                <div className="rounded-lg bg-white border border-gray-100 p-3">
                  <p className="text-xs font-semibold text-gray-700 mb-2">Token & Usage Volume</p>
                  <div className="h-52">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={tokenChartData}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} />
                        <Tooltip formatter={(value: number) => value.toLocaleString()} />
                        <Bar dataKey="value" fill="#4f46e5" radius={[6, 6, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {latencyChartData.length > 0 && (
                <div className="rounded-lg bg-white border border-gray-100 p-3">
                  <p className="text-xs font-semibold text-gray-700 mb-2">Latency Breakdown (ms)</p>
                  <div className="h-52">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={latencyChartData}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                        <YAxis tick={{ fontSize: 11 }} />
                        <Tooltip formatter={(value: number) => `${value.toFixed(1)} ms`} />
                        <Bar dataKey="value" fill="#06b6d4" radius={[6, 6, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {coreSections.map((section) => (
          <div key={section.title} className="rounded-xl border border-gray-100 bg-gray-50/40 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">{section.title}</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {section.items.map((item) => (
                <div key={`${section.title}-${item.label}`} className="rounded-lg bg-white border border-gray-100 p-3">
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">
                    {item.label}
                  </p>
                  <p className="text-sm text-gray-900 break-all">{item.value}</p>
                </div>
              ))}
            </div>
          </div>
        ))}

        {metricSections.length > 0 && (
          <details className="rounded-xl border border-gray-200 bg-white">
            <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-gray-800">
              Detailed Metric Tables
            </summary>
            <div className="border-t border-gray-100 p-4 space-y-4">
              {metricSections.map((section) => (
                <div key={section.title} className="rounded-xl border border-gray-100 bg-gray-50/40 p-4">
                  <h3 className="text-sm font-semibold text-gray-900 mb-3">{section.title}</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {section.items.map((item) => (
                      <div key={`${section.title}-${item.label}`} className="rounded-lg bg-white border border-gray-100 p-3">
                        <p className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">
                          {item.label}
                        </p>
                        <p className="text-sm text-gray-900 break-all">{item.value}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </details>
        )}

        <details className="rounded-xl border border-gray-200 bg-white">
          <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-gray-800">
            Raw Provider Payload
          </summary>
          <div className="border-t border-gray-100 p-4">
            <pre className="text-xs leading-relaxed text-gray-700 whitespace-pre-wrap break-words">
              {JSON.stringify(raw, null, 2)}
            </pre>
          </div>
        </details>
      </div>
    </div>
  )
}

function EventBadge({ event }: { event?: string }) {
  if (!event) return <span className="text-gray-400">&mdash;</span>
  const normalizedEvent = String(event).toLowerCase()

  const variants: Record<
    string,
    { label: string; bg: string; text: string; border: string; dot: string }
  > = {
    call_started: {
      label: 'Call Started',
      bg: 'bg-blue-50',
      text: 'text-blue-700',
      border: 'border-blue-200',
      dot: 'bg-blue-500',
    },
    call_ended: {
      label: 'Call Ended',
      bg: 'bg-emerald-50',
      text: 'text-emerald-700',
      border: 'border-emerald-200',
      dot: 'bg-emerald-500',
    },
    call_analyzed: {
      label: 'Call Analyzed',
      bg: 'bg-purple-50',
      text: 'text-purple-700',
      border: 'border-purple-200',
      dot: 'bg-purple-500',
    },
  }

  const variant = variants[normalizedEvent] || {
    label: String(event),
    bg: 'bg-gray-50',
    text: 'text-gray-600',
    border: 'border-gray-200',
    dot: 'bg-gray-400',
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${variant.bg} ${variant.text} ${variant.border}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${variant.dot}`} />
      {variant.label}
    </span>
  )
}

function EndReasonBadge({ reason }: { reason: string }) {
  const normalizedReason = String(reason || '').toLowerCase()
  const colors: Record<string, string> = {
    'customer-hungup': 'bg-amber-50 text-amber-700 border-amber-200',
    'assistant-ended-call': 'bg-blue-50 text-blue-700 border-blue-200',
    voicemail: 'bg-purple-50 text-purple-700 border-purple-200',
    error: 'bg-rose-50 text-rose-700 border-rose-200',
  }

  const colorClass = colors[normalizedReason] || 'bg-gray-50 text-gray-700 border-gray-200'
  const label = String(reason)
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (l) => l.toUpperCase())

  return (
    <span
      className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${colorClass}`}
    >
      {label}
    </span>
  )
}

function PlatformBadge({ platform }: { platform?: string }) {
  if (!platform) return <span className="text-gray-400">N/A</span>
  const normalized = String(platform).toLowerCase() as IntegrationPlatform
  const label = getIntegrationPlatformLabel(normalized)
  const logo = getIntegrationPlatformLogo(normalized)

  return (
    <span className="inline-flex items-center gap-2 text-sm text-gray-700">
      {logo && <img src={logo} alt={label} className="h-5 w-5 object-contain" />}
      <span>{label}</span>
    </span>
  )
}
