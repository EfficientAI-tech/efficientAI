import { useState, useMemo, useEffect, useRef } from 'react'
import {
  DollarSign, MessageSquare, TrendingUp, Activity, Server, CheckCircle, XCircle, Clock, Zap, Download, Loader
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts'

interface ElevenLabsTranscriptEntry {
  speaker: string
  text: string
  start: number
  end: number
}

interface ElevenLabsCallData {
  call_id?: string
  call_status?: string
  start_timestamp?: string
  end_timestamp?: string
  duration_seconds?: number
  transcript?: string
  transcript_object?: ElevenLabsTranscriptEntry[]
  analysis?: {
    summary?: string
    evaluation?: Record<string, any>
    data_collection?: Record<string, any>
    latency_stats?: Record<string, any>
    interruption_count?: number
  }
  cost?: number
  recording_urls?: {
    conversation_audio?: string
  }
  agent_id?: string
  raw_data?: {
    agent_name?: string
    status?: string
    metadata?: {
      start_time_unix_secs?: number
      call_duration_secs?: number
      cost?: number
      termination_reason?: string
      main_language?: string
      charging?: {
        llm_charge?: number
        call_charge?: number
        llm_price?: number
        tier?: string
        dev_discount?: boolean
        llm_usage?: {
          irreversible_generation?: {
            model_usage?: Record<string, {
              input?: { tokens?: number; price?: number }
              output_total?: { tokens?: number; price?: number }
            }>
          }
          initiated_generation?: {
            model_usage?: Record<string, {
              input?: { tokens?: number; price?: number }
              output_total?: { tokens?: number; price?: number }
            }>
          }
        }
      }
      feedback?: {
        overall_score?: number | null
        likes?: number
        dislikes?: number
      }
      features_usage?: Record<string, any>
      [key: string]: any
    }
    analysis?: {
      call_successful?: string
      transcript_summary?: string
      call_summary_title?: string
      evaluation_criteria_results?: Record<string, any>
      data_collection_results?: Record<string, any>
      [key: string]: any
    }
    transcript?: Array<{
      role: string
      message: string
      time_in_call_secs: number
      interrupted?: boolean
      conversation_turn_metrics?: {
        metrics?: Record<string, { elapsed_time?: number }>
        convai_asr_provider?: string | null
        convai_tts_model?: string | null
      }
      llm_usage?: {
        model_usage?: Record<string, {
          input?: { tokens?: number; price?: number }
          output_total?: { tokens?: number; price?: number }
        }>
      }
      [key: string]: any
    }>
    [key: string]: any
  }
}

interface ElevenLabsCallDetailsProps {
  callData: ElevenLabsCallData
  callShortId?: string
  hideTranscript?: boolean
}

const COLORS = ['#10b981', '#06b6d4', '#f59e0b', '#ef4444', '#8b5cf6']

export default function ElevenLabsCallDetails({ callData, callShortId, hideTranscript = false }: ElevenLabsCallDetailsProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'transcript'>('overview')
  const [audioBlobUrl, setAudioBlobUrl] = useState<string | null>(null)
  const [audioLoading, setAudioLoading] = useState(false)
  const [audioError, setAudioError] = useState(false)
  const audioFetched = useRef(false)
  const blobUrlRef = useRef<string | null>(null)

  const hasAudio = !!(callData.recording_urls?.conversation_audio)

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

  const formatDuration = (seconds?: number) => {
    if (!seconds) return 'N/A'
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = Math.floor(seconds % 60)
    return `${minutes}m ${remainingSeconds}s`
  }

  const formatTimestamp = (timestamp?: string) => {
    if (!timestamp) return 'N/A'
    return new Date(timestamp).toLocaleString()
  }

  const rawData = callData.raw_data
  const metadata = rawData?.metadata
  const charging = metadata?.charging
  const rawAnalysis = rawData?.analysis

  const transcriptEntries = callData.transcript_object || []

  // Build cost breakdown from charging data
  const costData = useMemo(() => {
    if (!charging) return []
    const items = []
    if (charging.call_charge) items.push({ name: 'Call (TTS + Infra)', value: charging.call_charge })
    if (charging.llm_charge) items.push({ name: 'LLM', value: charging.llm_charge })
    return items
  }, [charging])

  const totalCredits = callData.cost || (charging ? (charging.call_charge || 0) + (charging.llm_charge || 0) : 0)

  // Extract per-turn latency metrics from raw transcript
  const latencyData = useMemo(() => {
    const rawTranscript = rawData?.transcript
    if (!rawTranscript || !Array.isArray(rawTranscript)) return []

    const agentTurns = rawTranscript.filter(e => e.role === 'agent' && e.conversation_turn_metrics?.metrics)
    return agentTurns.map((entry, idx) => {
      const metrics = entry.conversation_turn_metrics!.metrics!
      return {
        name: `Turn ${idx + 1}`,
        time: entry.time_in_call_secs,
        llm_ttfb: metrics.convai_llm_service_ttfb?.elapsed_time
          ? Math.round(metrics.convai_llm_service_ttfb.elapsed_time * 1000) : undefined,
        tts_ttfb: metrics.convai_tts_service_ttfb?.elapsed_time
          ? Math.round(metrics.convai_tts_service_ttfb.elapsed_time * 1000) : undefined,
        llm_ttf_sentence: metrics.convai_llm_service_ttf_sentence?.elapsed_time
          ? Math.round(metrics.convai_llm_service_ttf_sentence.elapsed_time * 1000) : undefined,
      }
    }).filter(d => d.llm_ttfb !== undefined || d.tts_ttfb !== undefined)
  }, [rawData])

  // Compute aggregate latency stats
  const latencyStats = useMemo(() => {
    if (latencyData.length === 0) return null
    const llmValues = latencyData.map(d => d.llm_ttfb).filter((v): v is number => v !== undefined)
    const ttsValues = latencyData.map(d => d.tts_ttfb).filter((v): v is number => v !== undefined)

    const avg = (arr: number[]) => arr.length ? Math.round(arr.reduce((a, b) => a + b, 0) / arr.length) : undefined
    const min = (arr: number[]) => arr.length ? Math.min(...arr) : undefined
    const max = (arr: number[]) => arr.length ? Math.max(...arr) : undefined

    return {
      llm_avg: avg(llmValues),
      llm_min: min(llmValues),
      llm_max: max(llmValues),
      tts_avg: avg(ttsValues),
      tts_min: min(ttsValues),
      tts_max: max(ttsValues),
      turns: latencyData.length,
    }
  }, [latencyData])

  // Compute total LLM token usage
  const llmTokenUsage = useMemo(() => {
    const usage = charging?.llm_usage
    if (!usage) return null

    let totalInputTokens = 0
    let totalOutputTokens = 0
    let totalPrice = 0
    const models = new Set<string>()

    for (const gen of [usage.irreversible_generation, usage.initiated_generation]) {
      if (!gen?.model_usage) continue
      for (const [model, data] of Object.entries(gen.model_usage)) {
        models.add(model)
        totalInputTokens += (data.input?.tokens || 0) + ((data as any).input_cache_read?.tokens || 0)
        totalOutputTokens += data.output_total?.tokens || 0
        totalPrice += (data.input?.price || 0) + ((data as any).input_cache_read?.price || 0) + (data.output_total?.price || 0)
      }
    }

    return { totalInputTokens, totalOutputTokens, totalPrice, models: Array.from(models) }
  }, [charging])

  const SummaryCard = () => {
    const summary = rawAnalysis?.transcript_summary || callData.analysis?.summary
    const callSuccessful = rawAnalysis?.call_successful
    const terminationReason = metadata?.termination_reason
    const interruptionCount = callData.analysis?.interruption_count ?? 0

    // Count interrupted turns from raw transcript
    const interruptedTurns = rawData?.transcript?.filter(e => e.interrupted).length || interruptionCount

    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-emerald-600" />
          Call Analysis
        </h3>

        <div className="space-y-6">
          {summary && (
            <div className="p-4 bg-emerald-50 rounded-lg border border-emerald-100">
              <p className="text-sm font-medium text-emerald-900 mb-2">Summary</p>
              <p className="text-sm text-emerald-800 leading-relaxed">{summary}</p>
            </div>
          )}

          {rawAnalysis?.call_summary_title && (
            <div className="p-3 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Topic</p>
              <p className="text-sm font-medium text-gray-900">{rawAnalysis.call_summary_title}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Success</p>
              <div className="flex items-center gap-2">
                {callSuccessful === 'success' ? (
                  <span className="flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold text-green-700 bg-green-100">
                    <CheckCircle className="h-3 w-3" />
                    Successful
                  </span>
                ) : callSuccessful === 'failure' ? (
                  <span className="flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold text-red-700 bg-red-100">
                    <XCircle className="h-3 w-3" />
                    Unsuccessful
                  </span>
                ) : (
                  <span className="px-2 py-1 rounded-full text-xs font-semibold text-gray-700 bg-gray-100">
                    {callSuccessful || 'N/A'}
                  </span>
                )}
              </div>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Interruptions</p>
              <span className="text-lg font-bold text-gray-900">{interruptedTurns}</span>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Ended Reason</p>
              <span className="text-sm font-medium text-gray-900">
                {terminationReason?.replace(/:/g, ': ') || 'Normal'}
              </span>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Language</p>
              <span className="text-sm font-medium text-gray-900 uppercase">
                {metadata?.main_language || 'N/A'}
              </span>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const TranscriptCard = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col h-[600px]">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-emerald-600" />
          Transcript
        </h3>
        <div className="flex items-center gap-3">
          {rawData?.agent_name && (
            <span className="text-sm text-gray-500">
              Agent: <span className="font-medium text-gray-700">{rawData.agent_name}</span>
            </span>
          )}
          {audioLoading && (
            <Loader className="h-4 w-4 text-gray-400 animate-spin" />
          )}
          {audioBlobUrl && (
            <div className="flex items-center gap-2 bg-gray-100 rounded-full px-3 py-1">
              <audio controls src={audioBlobUrl} className="h-8 w-64" />
              <a href={audioBlobUrl} download={`call_${callShortId || 'recording'}.mp3`} className="text-gray-500 hover:text-emerald-600 p-1">
                <Download className="h-4 w-4" />
              </a>
            </div>
          )}
          {audioError && hasAudio && (
            <span className="text-xs text-gray-400">Audio unavailable</span>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pr-2 custom-scrollbar">
        {transcriptEntries.length > 0 ? (
          transcriptEntries.map((entry, idx) => {
            const isUser = entry.speaker === 'User'
            return (
              <div key={idx} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${isUser
                  ? 'bg-emerald-600 text-white rounded-br-none'
                  : 'bg-gray-100 text-gray-800 rounded-bl-none'
                  }`}>
                  <div className="flex items-center gap-2 mb-1 opacity-80">
                    <span className="text-xs font-semibold uppercase tracking-wider">
                      {isUser ? 'User' : (rawData?.agent_name || 'Agent')}
                    </span>
                    {entry.start > 0 && (
                      <span className="text-[10px]">
                        {entry.start.toFixed(0)}s
                      </span>
                    )}
                  </div>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{entry.text}</p>
                </div>
              </div>
            )
          })
        ) : callData.transcript ? (
          <div className="p-4 bg-gray-50 rounded-lg">
            <pre className="text-sm whitespace-pre-wrap text-gray-800 font-sans">
              {callData.transcript}
            </pre>
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">No transcript available</div>
        )}
      </div>
    </div>
  )

  const StatsParams = () => (
    <div className="space-y-6">
      {/* Cost Card */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <DollarSign className="h-5 w-5 text-emerald-600" />
          Cost Breakdown
        </h3>
        <div className="flex items-center justify-between">
          <div className="w-1/2">
            <div className="mb-4">
              <p className="text-sm text-gray-500">Total Cost</p>
              <p className="text-3xl font-bold text-gray-900">
                {totalCredits.toLocaleString()} <span className="text-sm font-normal text-gray-500">credits</span>
              </p>
              <p className="text-xs text-gray-500 mt-1">
                Duration: {formatDuration(callData.duration_seconds)}
              </p>
              {charging?.tier && (
                <p className="text-xs text-gray-400 mt-0.5">
                  Tier: <span className="capitalize">{charging.tier}</span>
                </p>
              )}
            </div>
            <div className="space-y-2">
              {charging?.call_charge !== undefined && (
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-600">Call (TTS + Infra)</span>
                  <span className="font-medium text-gray-900">{charging.call_charge.toLocaleString()}</span>
                </div>
              )}
              {charging?.llm_charge !== undefined && (
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-600">LLM</span>
                  <span className="font-medium text-gray-900">{charging.llm_charge.toLocaleString()}</span>
                </div>
              )}
              {charging?.llm_price !== undefined && (
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-600">LLM Price</span>
                  <span className="font-medium text-gray-900">${charging.llm_price.toFixed(6)}</span>
                </div>
              )}
            </div>

            {/* LLM Token Usage */}
            {llmTokenUsage && (
              <div className="mt-4 pt-4 border-t border-gray-200">
                <p className="text-xs text-gray-500 uppercase font-semibold mb-2">LLM Usage</p>
                <div className="space-y-1 text-xs">
                  {llmTokenUsage.models.length > 0 && (
                    <div className="flex justify-between">
                      <span className="text-gray-500">Model</span>
                      <span className="text-gray-700 font-mono">{llmTokenUsage.models.join(', ')}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-gray-500">Input Tokens</span>
                    <span className="text-gray-700">{llmTokenUsage.totalInputTokens.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Output Tokens</span>
                    <span className="text-gray-700">{llmTokenUsage.totalOutputTokens.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Total LLM Cost</span>
                    <span className="text-gray-700">${llmTokenUsage.totalPrice.toFixed(6)}</span>
                  </div>
                </div>
              </div>
            )}
          </div>
          <div className="w-1/2 h-40">
            {costData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={costData}
                    cx="50%"
                    cy="50%"
                    innerRadius={0}
                    outerRadius={60}
                    paddingAngle={5}
                    dataKey="value"
                  >
                    {costData.map((_entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value: number) => `${value.toLocaleString()} credits`} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                No cost data
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Latency Chart */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Activity className="h-5 w-5 text-emerald-600" />
          Latency Performance
        </h3>
        {latencyData.length > 0 ? (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={latencyData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis unit="ms" />
                <Tooltip
                  contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                  cursor={{ fill: '#F3F4F6' }}
                  formatter={(value: number) => `${value}ms`}
                />
                <Legend />
                <Bar dataKey="llm_ttfb" name="LLM TTFB" fill="#10b981" radius={[4, 4, 0, 0]} />
                <Bar dataKey="tts_ttfb" name="TTS TTFB" fill="#06b6d4" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">Latency data not available</div>
        )}

        {/* Aggregate Latency Stats */}
        {latencyStats && (
          <div className="mt-4 pt-4 border-t border-gray-200">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-gray-500 uppercase font-semibold mb-2 flex items-center gap-1">
                  <Zap className="h-3 w-3" /> LLM Latency
                </p>
                <div className="grid grid-cols-3 gap-2 text-center">
                  {latencyStats.llm_min !== undefined && (
                    <div>
                      <p className="text-xs text-gray-500">Min</p>
                      <p className="font-semibold text-gray-900">{latencyStats.llm_min}ms</p>
                    </div>
                  )}
                  {latencyStats.llm_avg !== undefined && (
                    <div>
                      <p className="text-xs text-gray-500">Avg</p>
                      <p className="font-semibold text-gray-900">{latencyStats.llm_avg}ms</p>
                    </div>
                  )}
                  {latencyStats.llm_max !== undefined && (
                    <div>
                      <p className="text-xs text-gray-500">Max</p>
                      <p className="font-semibold text-gray-900">{latencyStats.llm_max}ms</p>
                    </div>
                  )}
                </div>
              </div>
              <div>
                <p className="text-xs text-gray-500 uppercase font-semibold mb-2 flex items-center gap-1">
                  <Zap className="h-3 w-3" /> TTS Latency
                </p>
                <div className="grid grid-cols-3 gap-2 text-center">
                  {latencyStats.tts_min !== undefined && (
                    <div>
                      <p className="text-xs text-gray-500">Min</p>
                      <p className="font-semibold text-gray-900">{latencyStats.tts_min}ms</p>
                    </div>
                  )}
                  {latencyStats.tts_avg !== undefined && (
                    <div>
                      <p className="text-xs text-gray-500">Avg</p>
                      <p className="font-semibold text-gray-900">{latencyStats.tts_avg}ms</p>
                    </div>
                  )}
                  {latencyStats.tts_max !== undefined && (
                    <div>
                      <p className="text-xs text-gray-500">Max</p>
                      <p className="font-semibold text-gray-900">{latencyStats.tts_max}ms</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
            <div className="mt-3 text-center">
              <span className="text-xs text-gray-400">Agent turns: {latencyStats.turns}</span>
            </div>
          </div>
        )}
      </div>

      {/* System Info */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Server className="h-5 w-5 text-emerald-600" />
          System Details
        </h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-gray-500 mb-1">Conversation ID</p>
            <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 truncate text-xs">{callData.call_id}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Agent ID</p>
            <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 truncate text-xs">{callData.agent_id}</p>
          </div>
          {rawData?.agent_name && (
            <div>
              <p className="text-gray-500 mb-1">Agent Name</p>
              <p className="text-gray-700">{rawData.agent_name}</p>
            </div>
          )}
          <div>
            <p className="text-gray-500 mb-1 flex items-center gap-1"><Clock className="h-3 w-3" /> Start Time</p>
            <p className="text-gray-700 text-xs">{formatTimestamp(callData.start_timestamp)}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1 flex items-center gap-1"><Clock className="h-3 w-3" /> End Time</p>
            <p className="text-gray-700 text-xs">{formatTimestamp(callData.end_timestamp)}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Duration</p>
            <p className="text-gray-700">{formatDuration(callData.duration_seconds)}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Status</p>
            <p className="text-gray-700 capitalize">{callData.call_status}</p>
          </div>
          {rawData?.transcript?.[0]?.conversation_turn_metrics?.convai_tts_model && (
            <div>
              <p className="text-gray-500 mb-1">TTS Model</p>
              <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 text-xs">
                {rawData.transcript[0].conversation_turn_metrics.convai_tts_model}
              </p>
            </div>
          )}
          {rawData?.transcript?.some(e => e.conversation_turn_metrics?.convai_asr_provider) && (
            <div>
              <p className="text-gray-500 mb-1">ASR Provider</p>
              <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 text-xs">
                {rawData.transcript.find(e => e.conversation_turn_metrics?.convai_asr_provider)?.conversation_turn_metrics?.convai_asr_provider}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )

  if (hideTranscript) {
    return (
      <div className="space-y-6">
        <SummaryCard />
        <StatsParams />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Navigation Tabs */}
      <div className="flex border-b border-gray-200">
        <button
          onClick={() => setActiveTab('overview')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === 'overview'
            ? 'border-emerald-600 text-emerald-600'
            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
        >
          Overview
        </button>
        <button
          onClick={() => setActiveTab('transcript')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === 'transcript'
            ? 'border-emerald-600 text-emerald-600'
            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
        >
          Transcript
        </button>
      </div>

      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <SummaryCard />
            <TranscriptCard />
          </div>
          <div className="lg:col-span-1">
            <StatsParams />
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
