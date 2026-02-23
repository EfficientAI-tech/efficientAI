import { useState } from 'react'
import {
  DollarSign, MessageSquare, TrendingUp, Download, Activity, Server, CheckCircle, XCircle
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts'

interface VapiTranscriptEntry {
  role: string
  content: string
  seconds_from_start?: number
  duration_ms?: number
  time_ms?: number
  end_time_ms?: number
  words?: Array<{
    word: string
    start: number
    end: number
    confidence?: number
    punctuated_word?: string
  }>
}

interface VapiCallData {
  call_id?: string
  call_status?: string
  call_type?: string
  assistant_id?: string
  start_timestamp?: string
  end_timestamp?: string
  duration_seconds?: number
  cost?: number
  cost_breakdown?: {
    transport?: number
    stt?: number
    llm?: number
    tts?: number
    vapi?: number
    total?: number
    llm_prompt_tokens?: number
    llm_completion_tokens?: number
    llm_cached_prompt_tokens?: number
    tts_characters?: number
    analysis?: {
      summary?: number
      success_evaluation?: number
      structured_data?: number
    }
  }
  transcript?: string
  transcript_object?: VapiTranscriptEntry[]
  messages?: Array<{
    role: string
    message?: string
    content?: string
    time?: number
    endTime?: number
    duration?: number
    secondsFromStart?: number
    metadata?: any
  }>
  analysis?: {
    summary?: string
    success_evaluation?: string | boolean
    latency_stats?: {
      model_latency_avg?: number
      voice_latency_avg?: number
      transcriber_latency_avg?: number
      endpointing_latency_avg?: number
      turn_latency_avg?: number
      from_transport_latency_avg?: number
      to_transport_latency_avg?: number
      num_assistant_interrupted?: number
      p50?: number
      p90?: number
      p95?: number
      p99?: number
      max?: number
      min?: number
      num_turns?: number
      turn_latencies?: Array<{
        modelLatency?: number
        voiceLatency?: number
        transcriberLatency?: number
        endpointingLatency?: number
        turnLatency?: number
      }>
    }
    interruption_count?: number
  }
  recording_urls?: {
    combined_url?: string
    stereo_url?: string
    assistant_url?: string
    customer_url?: string
  }
  ended_reason?: string
  metadata?: Record<string, any>
  raw_data?: any
}

interface VapiCallDetailsProps {
  callData: VapiCallData
  hideTranscript?: boolean
}

const COLORS = ['#8b5cf6', '#06b6d4', '#f59e0b', '#ef4444', '#10b981'];

export default function VapiCallDetails({ callData, hideTranscript = false }: VapiCallDetailsProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'transcript'>('overview')

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

  // Get recording URL - prefer combined, then stereo
  const recordingUrl = callData.recording_urls?.combined_url || 
                       callData.recording_urls?.stereo_url ||
                       callData.raw_data?.recordingUrl ||
                       callData.raw_data?.stereoRecordingUrl

  // Prepare transcript for display
  const transcriptEntries = callData.transcript_object || []
  
  // Prepare latency data for chart
  const latencyStats = callData.analysis?.latency_stats
  const latencyData = [
    { name: 'Model', avg: latencyStats?.model_latency_avg, p50: latencyStats?.p50 },
    { name: 'Voice', avg: latencyStats?.voice_latency_avg },
    { name: 'Transcriber', avg: latencyStats?.transcriber_latency_avg },
    { name: 'Endpointing', avg: latencyStats?.endpointing_latency_avg },
    { name: 'Turn Total', avg: latencyStats?.turn_latency_avg, p90: latencyStats?.p90 },
  ].filter(item => item.avg !== undefined && item.avg !== null)

  // Prepare cost data for pie chart
  const costBreakdown = callData.cost_breakdown
  const costData = [
    { name: 'Transport', value: costBreakdown?.transport || 0 },
    { name: 'STT', value: costBreakdown?.stt || 0 },
    { name: 'LLM', value: costBreakdown?.llm || 0 },
    { name: 'TTS', value: costBreakdown?.tts || 0 },
    { name: 'Vapi', value: costBreakdown?.vapi || 0 },
  ].filter(item => item.value > 0)

  const SummaryCard = () => {
    const analysis = callData.analysis
    const successEval = analysis?.success_evaluation
    const isSuccessful = successEval === true || successEval === 'true'
    
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-violet-600" />
          Call Analysis
        </h3>

        {analysis ? (
          <div className="space-y-6">
            {analysis.summary && (
              <div className="p-4 bg-violet-50 rounded-lg border border-violet-100">
                <p className="text-sm font-medium text-violet-900 mb-2">Summary</p>
                <p className="text-sm text-violet-800 leading-relaxed">
                  {analysis.summary}
                </p>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 bg-gray-50 rounded-lg">
                <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Success</p>
                <div className="flex items-center gap-2">
                  {isSuccessful ? (
                    <span className="flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold text-green-700 bg-green-100">
                      <CheckCircle className="h-3 w-3" />
                      Successful
                    </span>
                  ) : successEval === false || successEval === 'false' ? (
                    <span className="flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold text-red-700 bg-red-100">
                      <XCircle className="h-3 w-3" />
                      Unsuccessful
                    </span>
                  ) : (
                    <span className="px-2 py-1 rounded-full text-xs font-semibold text-gray-700 bg-gray-100">
                      N/A
                    </span>
                  )}
                </div>
              </div>

              <div className="p-4 bg-gray-50 rounded-lg">
                <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Interruptions</p>
                <span className="text-lg font-bold text-gray-900">
                  {analysis.interruption_count ?? 0}
                </span>
              </div>

              <div className="p-4 bg-gray-50 rounded-lg">
                <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Ended Reason</p>
                <span className="text-sm font-medium text-gray-900 capitalize">
                  {callData.ended_reason?.replace(/-/g, ' ') || 'Normal'}
                </span>
              </div>

              <div className="p-4 bg-gray-50 rounded-lg">
                <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Call Type</p>
                <span className="text-sm font-medium text-gray-900 capitalize">
                  {callData.call_type || 'Web Call'}
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">Analysis not available</div>
        )}
      </div>
    )
  }

  const TranscriptCard = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col h-[600px]">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-violet-600" />
          Transcript
        </h3>
        {recordingUrl && (
          <div className="flex items-center gap-2 bg-gray-100 rounded-full px-3 py-1">
            <audio controls src={recordingUrl} className="h-8 w-64" />
            <a href={recordingUrl} download className="text-gray-500 hover:text-violet-600 p-1">
              <Download className="h-4 w-4" />
            </a>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pr-2 custom-scrollbar">
        {transcriptEntries.length > 0 ? (
          transcriptEntries.map((msg, idx) => {
            const isUser = msg.role === 'user'
            const isAgent = msg.role === 'agent' || msg.role === 'bot' || msg.role === 'assistant'
            
            if (!isUser && !isAgent) return null
            
            return (
              <div key={idx} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${isUser
                  ? 'bg-violet-600 text-white rounded-br-none'
                  : 'bg-gray-100 text-gray-800 rounded-bl-none'
                  }`}>
                  <div className="flex items-center gap-2 mb-1 opacity-80">
                    <span className="text-xs font-semibold uppercase tracking-wider">
                      {isUser ? 'User' : 'Agent'}
                    </span>
                    {msg.seconds_from_start !== undefined && (
                      <span className="text-[10px]">
                        {msg.seconds_from_start.toFixed(1)}s
                      </span>
                    )}
                  </div>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                </div>
              </div>
            )
          })
        ) : callData.transcript ? (
          // Fallback to plain transcript if no transcript_object
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
          <DollarSign className="h-5 w-5 text-violet-600" />
          Cost Breakdown
        </h3>
        <div className="flex items-center justify-between">
          <div className="w-1/2">
            <div className="mb-4">
              <p className="text-sm text-gray-500">Total Cost</p>
              <p className="text-3xl font-bold text-gray-900">
                ${callData.cost?.toFixed(4) || costBreakdown?.total?.toFixed(4) || '0.0000'}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                Duration: {formatDuration(callData.duration_seconds)}
              </p>
            </div>
            <div className="space-y-2">
              {costBreakdown?.transport !== undefined && (
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-600">Transport</span>
                  <span className="font-medium text-gray-900">${costBreakdown.transport.toFixed(4)}</span>
                </div>
              )}
              {costBreakdown?.stt !== undefined && (
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-600">STT (Speech-to-Text)</span>
                  <span className="font-medium text-gray-900">${costBreakdown.stt.toFixed(4)}</span>
                </div>
              )}
              {costBreakdown?.llm !== undefined && (
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-600">LLM</span>
                  <span className="font-medium text-gray-900">${costBreakdown.llm.toFixed(4)}</span>
                </div>
              )}
              {costBreakdown?.tts !== undefined && (
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-600">TTS (Text-to-Speech)</span>
                  <span className="font-medium text-gray-900">${costBreakdown.tts.toFixed(4)}</span>
                </div>
              )}
              {costBreakdown?.vapi !== undefined && (
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-600">Vapi Fee</span>
                  <span className="font-medium text-gray-900">${costBreakdown.vapi.toFixed(4)}</span>
                </div>
              )}
            </div>
            {/* Token Usage */}
            {(costBreakdown?.llm_prompt_tokens || costBreakdown?.tts_characters) && (
              <div className="mt-4 pt-4 border-t border-gray-200">
                <p className="text-xs text-gray-500 uppercase font-semibold mb-2">Usage</p>
                <div className="space-y-1 text-xs">
                  {costBreakdown.llm_prompt_tokens && (
                    <div className="flex justify-between">
                      <span className="text-gray-500">LLM Prompt Tokens</span>
                      <span className="text-gray-700">{costBreakdown.llm_prompt_tokens.toLocaleString()}</span>
                    </div>
                  )}
                  {costBreakdown.llm_completion_tokens && (
                    <div className="flex justify-between">
                      <span className="text-gray-500">LLM Completion Tokens</span>
                      <span className="text-gray-700">{costBreakdown.llm_completion_tokens.toLocaleString()}</span>
                    </div>
                  )}
                  {costBreakdown.tts_characters && (
                    <div className="flex justify-between">
                      <span className="text-gray-500">TTS Characters</span>
                      <span className="text-gray-700">{costBreakdown.tts_characters.toLocaleString()}</span>
                    </div>
                  )}
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
                  <Tooltip formatter={(value: number) => `$${value.toFixed(4)}`} />
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
          <Activity className="h-5 w-5 text-violet-600" />
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
                />
                <Legend />
                <Bar dataKey="avg" name="Avg (ms)" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                {latencyStats?.p90 && <Bar dataKey="p90" name="P90 (ms)" fill="#6d28d9" radius={[4, 4, 0, 0]} />}
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">Latency data not available</div>
        )}

        {/* Latency Stats Grid */}
        {latencyStats && (
          <div className="mt-4 pt-4 border-t border-gray-200 grid grid-cols-3 gap-3 text-center">
            {latencyStats.p50 && (
              <div>
                <p className="text-xs text-gray-500">P50</p>
                <p className="font-semibold text-gray-900">{latencyStats.p50.toFixed(0)}ms</p>
              </div>
            )}
            {latencyStats.p90 && (
              <div>
                <p className="text-xs text-gray-500">P90</p>
                <p className="font-semibold text-gray-900">{latencyStats.p90.toFixed(0)}ms</p>
              </div>
            )}
            {latencyStats.p99 && (
              <div>
                <p className="text-xs text-gray-500">P99</p>
                <p className="font-semibold text-gray-900">{latencyStats.p99.toFixed(0)}ms</p>
              </div>
            )}
            {latencyStats.num_turns && (
              <div>
                <p className="text-xs text-gray-500">Turns</p>
                <p className="font-semibold text-gray-900">{latencyStats.num_turns}</p>
              </div>
            )}
            {latencyStats.min && (
              <div>
                <p className="text-xs text-gray-500">Min</p>
                <p className="font-semibold text-gray-900">{latencyStats.min.toFixed(0)}ms</p>
              </div>
            )}
            {latencyStats.max && (
              <div>
                <p className="text-xs text-gray-500">Max</p>
                <p className="font-semibold text-gray-900">{latencyStats.max.toFixed(0)}ms</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* System Info */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Server className="h-5 w-5 text-violet-600" />
          System Details
        </h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-gray-500 mb-1">Call ID</p>
            <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 truncate text-xs">{callData.call_id}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Assistant ID</p>
            <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 truncate text-xs">{callData.assistant_id}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Start Time</p>
            <p className="text-gray-700 text-xs">{formatTimestamp(callData.start_timestamp)}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1">End Time</p>
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
        </div>

        {/* Recording URLs */}
        {callData.recording_urls && Object.values(callData.recording_urls).some(Boolean) && (
          <div className="mt-4 pt-4 border-t border-gray-200">
            <p className="text-xs text-gray-500 uppercase font-semibold mb-2">Recordings</p>
            <div className="space-y-2">
              {callData.recording_urls.combined_url && (
                <a 
                  href={callData.recording_urls.combined_url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 text-xs text-violet-600 hover:text-violet-800"
                >
                  <Download className="h-3 w-3" />
                  Combined (Mono)
                </a>
              )}
              {callData.recording_urls.stereo_url && (
                <a 
                  href={callData.recording_urls.stereo_url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 text-xs text-violet-600 hover:text-violet-800"
                >
                  <Download className="h-3 w-3" />
                  Stereo
                </a>
              )}
              {callData.recording_urls.assistant_url && (
                <a 
                  href={callData.recording_urls.assistant_url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 text-xs text-violet-600 hover:text-violet-800"
                >
                  <Download className="h-3 w-3" />
                  Assistant Only
                </a>
              )}
              {callData.recording_urls.customer_url && (
                <a 
                  href={callData.recording_urls.customer_url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 text-xs text-violet-600 hover:text-violet-800"
                >
                  <Download className="h-3 w-3" />
                  Customer Only
                </a>
              )}
            </div>
          </div>
        )}
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
            ? 'border-violet-600 text-violet-600'
            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
        >
          Overview
        </button>
        <button
          onClick={() => setActiveTab('transcript')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === 'transcript'
            ? 'border-violet-600 text-violet-600'
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
