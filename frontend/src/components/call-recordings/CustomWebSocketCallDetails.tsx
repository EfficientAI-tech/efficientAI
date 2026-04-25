import { useState, useEffect, useRef, useMemo } from 'react'
import {
  MessageSquare,
  Clock,
  Globe,
  Download,
  Loader,
  TrendingUp,
  CheckCircle,
  Server,
  RefreshCw,
  AlertCircle,
  Sparkles,
} from 'lucide-react'
import { apiClient } from '../../lib/api'

interface SpeakerSegment {
  speaker: string
  text: string
  start: number
  end: number
}

interface CustomWSCallData {
  source?: string
  websocket_url?: string
  messages?: Array<{ role: string; content: string; timestamp?: string }>
  transcript?: string
  speaker_segments?: SpeakerSegment[]
  recording_s3_key?: string | null
  started_at?: string | null
  ended_at?: string | null
  duration_seconds?: number
}

interface Props {
  callData: CustomWSCallData
  callShortId?: string
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function formatTimestamp(ts?: string | null): string {
  if (!ts) return 'N/A'
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return 'N/A'
  }
}

const isUserSpeaker = (speaker: string) =>
  speaker === 'user' || speaker === 'Speaker 1' || speaker === 'caller'

const getSpeakerLabel = (speaker: string) =>
  isUserSpeaker(speaker) ? 'You' : 'Agent'

export default function CustomWebSocketCallDetails({ callData, callShortId }: Props) {
  const [activeTab, setActiveTab] = useState<'overview' | 'transcript'>('overview')
  const [audioBlobUrl, setAudioBlobUrl] = useState<string | null>(null)
  const [audioLoading, setAudioLoading] = useState(false)
  const [audioError, setAudioError] = useState(false)
  const audioFetched = useRef(false)
  const blobUrlRef = useRef<string | null>(null)

  const [llmSummary, setLlmSummary] = useState<string | null>(null)
  const [summaryProvider, setSummaryProvider] = useState<{
    provider?: string
    model?: string
    source?: 'voice_bundle' | 'org_fallback'
  } | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const summaryFetched = useRef(false)

  const hasAudio = !!callData.recording_s3_key
  const duration = callData.duration_seconds || 0
  const segments = callData.speaker_segments || []
  const messages = callData.messages || []

  useEffect(() => {
    if (!callShortId || !hasAudio || audioFetched.current) return
    audioFetched.current = true
    setAudioLoading(true)
    apiClient.getCallRecordingAudioUrl(callShortId)
      .then(url => {
        blobUrlRef.current = url
        setAudioBlobUrl(url)
      })
      .catch(() => setAudioError(true))
      .finally(() => setAudioLoading(false))

    return () => {
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current)
    }
  }, [callShortId, hasAudio])

  const { userTurns, agentTurns } = useMemo(() => {
    const userSegs = segments.filter(s => isUserSpeaker(s.speaker))
    const agentSegs = segments.filter(s => !isUserSpeaker(s.speaker))
    return {
      userTurns: userSegs.length,
      agentTurns: agentSegs.length,
    }
  }, [segments])

  const entriesForSummary = useMemo(() => {
    if (messages.length > 0) {
      return messages.map(m => ({
        role: m.role,
        content: m.content,
        timestamp: m.timestamp,
      }))
    }
    if (segments.length > 0) {
      return segments.map(s => ({
        role: isUserSpeaker(s.speaker) ? 'user' : 'agent',
        content: s.text,
      }))
    }
    return []
  }, [messages, segments])

  const transcriptForSummary = (callData.transcript || '').trim()
  const hasTranscript = entriesForSummary.length > 0 || transcriptForSummary.length > 0

  const fetchSummary = async (opts?: { force?: boolean }) => {
    if (!hasTranscript) return
    setSummaryLoading(true)
    setSummaryError(null)
    try {
      const res = await apiClient.summarizeTranscript({
        entries: entriesForSummary.length > 0 ? entriesForSummary : undefined,
        transcript: entriesForSummary.length === 0 ? transcriptForSummary : undefined,
        callShortId,
        force: opts?.force,
      })
      setLlmSummary(res.summary)
      setSummaryProvider({ provider: res.provider, model: res.model, source: res.source })
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        'Failed to generate summary'
      setSummaryError(msg)
    } finally {
      setSummaryLoading(false)
    }
  }

  useEffect(() => {
    if (summaryFetched.current) return
    if (!hasTranscript) return
    summaryFetched.current = true
    fetchSummary()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasTranscript])

  const tabs = [
    { id: 'overview' as const, label: 'Overview' },
    { id: 'transcript' as const, label: 'Transcript' },
  ]

  const SummaryCard = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-indigo-600" />
          Session Summary
        </h3>
        {hasTranscript && (
          <button
            type="button"
            onClick={() => fetchSummary({ force: true })}
            disabled={summaryLoading}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-700 disabled:opacity-50"
            title="Regenerate summary"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${summaryLoading ? 'animate-spin' : ''}`} />
            {summaryLoading ? 'Summarizing…' : 'Regenerate'}
          </button>
        )}
      </div>

      <div className="space-y-4">
        <div className="p-4 bg-indigo-50 rounded-lg border border-indigo-100">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm font-medium text-indigo-900 flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5" />
              AI Summary
            </p>
            {summaryProvider?.provider && !summaryLoading && (
              <div className="flex items-center gap-1.5">
                {summaryProvider.source === 'voice_bundle' && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded">
                    voice bundle
                  </span>
                )}
                {summaryProvider.source === 'org_fallback' && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded">
                    org fallback
                  </span>
                )}
                <span className="text-[10px] px-1.5 py-0.5 bg-indigo-100 text-indigo-700 rounded font-mono">
                  {summaryProvider.provider}
                  {summaryProvider.model ? ` · ${summaryProvider.model}` : ''}
                </span>
              </div>
            )}
          </div>

          {summaryLoading && !llmSummary ? (
            <div className="flex items-center gap-2 text-sm text-indigo-800">
              <Loader className="h-4 w-4 animate-spin" />
              <span>Generating summary with LLM…</span>
            </div>
          ) : summaryError ? (
            <div className="flex items-start gap-2 text-sm text-red-700">
              <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <span>{summaryError}</span>
            </div>
          ) : llmSummary ? (
            <p className="text-sm text-indigo-800 leading-relaxed whitespace-pre-wrap">{llmSummary}</p>
          ) : !hasTranscript ? (
            <p className="text-sm text-indigo-800/70">No transcript available to summarize.</p>
          ) : (
            <p className="text-sm text-indigo-800/70">Summary will appear here shortly.</p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="p-3 bg-gray-50 rounded-lg">
            <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">Status</p>
            <div className="flex items-center gap-1.5">
              <CheckCircle className="h-3.5 w-3.5 text-green-600" />
              <span className="text-sm font-medium text-gray-900">
                {segments.length > 0 ? 'Completed' : 'No transcript'}
              </span>
            </div>
          </div>
          <div className="p-3 bg-gray-50 rounded-lg">
            <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">User / Agent turns</p>
            <p className="text-sm font-medium text-gray-900">{userTurns} / {agentTurns}</p>
          </div>
        </div>
      </div>
    </div>
  )

  const TranscriptCard = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col h-[600px]">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-indigo-600" />
          Transcript
        </h3>
        <div className="flex items-center gap-3">
          {audioLoading && <Loader className="h-4 w-4 text-gray-400 animate-spin" />}
          {audioBlobUrl && (
            <div className="flex items-center gap-2 bg-gray-100 rounded-full px-3 py-1">
              <audio controls src={audioBlobUrl} className="h-8 w-64" />
              <a
                href={audioBlobUrl}
                download={`call_${callShortId || 'recording'}.webm`}
                className="text-gray-500 hover:text-indigo-600 p-1"
              >
                <Download className="h-4 w-4" />
              </a>
            </div>
          )}
          {audioError && hasAudio && (
            <span className="text-xs text-gray-400">Audio unavailable</span>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pr-2">
        {segments.length > 0 ? (
          segments.map((seg, idx) => (
            <div key={idx} className={`flex ${isUserSpeaker(seg.speaker) ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                isUserSpeaker(seg.speaker)
                  ? 'bg-indigo-600 text-white rounded-br-none'
                  : 'bg-gray-100 text-gray-800 rounded-bl-none'
              }`}>
                <div className="flex items-center gap-2 mb-1 opacity-80">
                  <span className="text-xs font-semibold uppercase tracking-wider">
                    {getSpeakerLabel(seg.speaker)}
                  </span>
                </div>
                <p className="text-sm leading-relaxed whitespace-pre-wrap">{seg.text}</p>
              </div>
            </div>
          ))
        ) : callData.transcript ? (
          <div className="p-4 bg-gray-50 rounded-lg">
            <pre className="text-sm whitespace-pre-wrap text-gray-800 font-sans">
              {callData.transcript}
            </pre>
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">
            No transcript available
          </div>
        )}
      </div>
    </div>
  )

  const SessionDetailsCard = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <Server className="h-5 w-5 text-indigo-600" />
        Session Details
      </h3>
      <div className="grid grid-cols-1 gap-4 text-sm">
        <div>
          <p className="text-gray-500 mb-1 flex items-center gap-1">
            <Globe className="h-3 w-3" /> WebSocket URL
          </p>
          <p className="font-mono bg-gray-50 p-1.5 rounded text-gray-700 text-xs break-all">
            {callData.websocket_url || 'N/A'}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-gray-500 mb-1 flex items-center gap-1">
              <Clock className="h-3 w-3" /> Duration
            </p>
            <p className="text-gray-700">
              {duration > 0 ? formatDuration(duration) : 'N/A'}
            </p>
          </div>
          <div>
            <p className="text-gray-500 mb-1 flex items-center gap-1">
              <MessageSquare className="h-3 w-3" /> Messages
            </p>
            <p className="text-gray-700">{messages.length}</p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-gray-500 mb-1 flex items-center gap-1">
              <Clock className="h-3 w-3" /> Started
            </p>
            <p className="text-gray-700 text-xs">
              {formatTimestamp(callData.started_at)}
            </p>
          </div>
          <div>
            <p className="text-gray-500 mb-1 flex items-center gap-1">
              <Clock className="h-3 w-3" /> Ended
            </p>
            <p className="text-gray-700 text-xs">
              {formatTimestamp(callData.ended_at)}
            </p>
          </div>
        </div>
        {callShortId && (
          <div>
            <p className="text-gray-500 mb-1">Call ID</p>
            <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 text-xs">{callShortId}</p>
          </div>
        )}
      </div>
    </div>
  )

  return (
    <div>
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-gray-900">Custom WebSocket Session</h2>
      </div>

      {/* Tab navigation */}
      <div className="flex border-b border-gray-200 mb-4">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <SummaryCard />
            <TranscriptCard />
          </div>
          <div className="lg:col-span-1">
            <SessionDetailsCard />
          </div>
        </div>
      )}

      {activeTab === 'transcript' && (
        <div className="space-y-6">
          <TranscriptCard />
        </div>
      )}
    </div>
  )
}
