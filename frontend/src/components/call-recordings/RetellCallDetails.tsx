import { useState } from 'react'
import {
  DollarSign, MessageSquare, TrendingUp, Download, Activity, Server
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts'

interface RetellCallData {
  call_type?: string
  call_id?: string
  agent_id?: string
  agent_name?: string
  call_status?: string
  start_timestamp?: number
  end_timestamp?: number
  duration_ms?: number
  transcript?: string
  transcript_object?: Array<{
    role: string
    content: string
    words?: Array<{
      word: string
      start: number
      end: number
    }>
  }>
  recording_url?: string
  recording_multi_channel_url?: string
  latency?: {
    e2e?: { p50?: number; p90?: number; p95?: number; p99?: number; max?: number; min?: number }
    asr?: { p50?: number; p90?: number; p95?: number; p99?: number; max?: number; min?: number }
    llm?: { p50?: number; p90?: number; p95?: number; p99?: number; max?: number; min?: number }
    tts?: { p50?: number; p90?: number; p95?: number; p99?: number; max?: number; min?: number }
  }
  call_cost?: {
    total_duration_seconds?: number
    combined_cost?: number
    product_costs?: Array<{
      product: string
      cost: number
      unit_price: number
    }>
  }
  call_analysis?: {
    call_summary?: string
    in_voicemail?: boolean
    user_sentiment?: string
    call_successful?: boolean
  }
  disconnection_reason?: string
  transfer_destination?: string
  metadata?: Record<string, any>
  retell_llm_dynamic_variables?: Record<string, any>
  collected_dynamic_variables?: Record<string, any>
}

interface RetellCallDetailsProps {
  callData: RetellCallData
}

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8'];

export default function RetellCallDetails({ callData }: RetellCallDetailsProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'transcript' | 'debug'>('overview')

  const formatDuration = (ms?: number) => {
    if (!ms) return 'N/A'
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}m ${remainingSeconds}s`
  }

  const formatTimestamp = (timestamp?: number) => {
    if (!timestamp) return 'N/A'
    return new Date(timestamp).toLocaleString()
  }

  const getSentimentColor = (sentiment?: string) => {
    if (!sentiment) return 'text-gray-500 bg-gray-100'
    const s = sentiment.toLowerCase()
    if (s.includes('positive') || s.includes('happy')) return 'text-green-700 bg-green-100'
    if (s.includes('negative') || s.includes('angry')) return 'text-red-700 bg-red-100'
    return 'text-blue-700 bg-blue-100'
  }

  // Prepare Chart Data
  const latencyData = [
    { name: 'E2E', p50: callData.latency?.e2e?.p50, p90: callData.latency?.e2e?.p90, max: callData.latency?.e2e?.max },
    { name: 'ASR', p50: callData.latency?.asr?.p50, p90: callData.latency?.asr?.p90, max: callData.latency?.asr?.max },
    { name: 'LLM', p50: callData.latency?.llm?.p50, p90: callData.latency?.llm?.p90, max: callData.latency?.llm?.max },
    { name: 'TTS', p50: callData.latency?.tts?.p50, p90: callData.latency?.tts?.p90, max: callData.latency?.tts?.max },
  ].filter(item => item.p50 !== undefined)

  const costData = callData.call_cost?.product_costs?.map(item => ({
    name: item.product,
    value: item.cost
  })) || []

  const SummaryCard = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <TrendingUp className="h-5 w-5 text-indigo-600" />
        Call Analysis
      </h3>

      {callData.call_analysis ? (
        <div className="space-y-6">
          <div className="p-4 bg-indigo-50 rounded-lg border border-indigo-100">
            <p className="text-sm font-medium text-indigo-900 mb-2">Summary</p>
            <p className="text-sm text-indigo-800 leading-relaxed">
              {callData.call_analysis.call_summary || "No summary available."}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Sentiment</p>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-1 rounded-full text-xs font-semibold ${getSentimentColor(callData.call_analysis.user_sentiment)}`}>
                  {callData.call_analysis.user_sentiment || 'Neutral'}
                </span>
              </div>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Success Status</p>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-1 rounded-full text-xs font-semibold ${callData.call_analysis.call_successful
                  ? 'text-green-700 bg-green-100'
                  : 'text-yellow-700 bg-yellow-100'
                  }`}>
                  {callData.call_analysis.call_successful ? 'Successful' : 'Unsuccessful'}
                </span>
              </div>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Voicemail</p>
              <span className="text-sm font-medium text-gray-900">
                {callData.call_analysis.in_voicemail ? 'Yes' : 'No'}
              </span>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Ended Reason</p>
              <span className="text-sm font-medium text-gray-900 capitalize">
                {callData.disconnection_reason?.replace(/_/g, ' ') || 'Normal'}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="text-center py-8 text-gray-500">Analysis not available</div>
      )}
    </div>
  )

  const TranscriptCard = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col h-[600px]">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-indigo-600" />
          Transcript
        </h3>
        {callData.recording_url && (
          <div className="flex items-center gap-2 bg-gray-100 rounded-full px-3 py-1">
            <audio controls src={callData.recording_url} className="h-8 w-64" />
            <a href={callData.recording_url} download className="text-gray-500 hover:text-indigo-600 p-1">
              <Download className="h-4 w-4" />
            </a>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pr-2 custom-scrollbar">
        {callData.transcript_object?.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${msg.role === 'user'
              ? 'bg-indigo-600 text-white rounded-br-none'
              : 'bg-gray-100 text-gray-800 rounded-bl-none'
              }`}>
              <div className="flex items-center gap-2 mb-1 opacity-80">
                <span className="text-xs font-semibold uppercase tracking-wider">
                  {msg.role === 'user' ? 'User' : (callData.agent_name || 'Agent')}
                </span>
                {msg.words && msg.words.length > 0 && (
                  <span className="text-[10px]">
                    {msg.words[0].start.toFixed(1)}s
                  </span>
                )}
              </div>
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )

  const StatsParams = () => (
    <div className="space-y-6">
      {/* Cost Card */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <DollarSign className="h-5 w-5 text-indigo-600" />
          Cost Breakdown
        </h3>
        <div className="flex items-center justify-between">
          <div className="w-1/2">
            <div className="mb-4">
              <p className="text-sm text-gray-500">Total Cost</p>
              <p className="text-3xl font-bold text-gray-900">
                ${callData.call_cost?.combined_cost?.toFixed(3) || '0.000'}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                Duration: {callData.call_cost?.total_duration_seconds}s
              </p>
            </div>
            <div className="space-y-2">
              {callData.call_cost?.product_costs?.map((prod, i) => (
                <div key={i} className="flex justify-between items-center text-sm">
                  <span className="text-gray-600 capitalize">{prod.product.replace(/_/g, ' ')}</span>
                  <span className="font-medium text-gray-900">${prod.cost.toFixed(3)}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="w-1/2 h-40">
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
                <Tooltip formatter={(value: number) => `$${value.toFixed(3)}`} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Latency Chart */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Activity className="h-5 w-5 text-indigo-600" />
          Latency Performance
        </h3>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={latencyData}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="name" />
              <YAxis unit="ms" />
              <Tooltip
                contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                cursor={{ fill: '#F3F4F6' }}
              />
              <Legend />
              <Bar dataKey="p50" name="P50 (ms)" fill="#818cf8" radius={[4, 4, 0, 0]} />
              <Bar dataKey="p90" name="P90 (ms)" fill="#4f46e5" radius={[4, 4, 0, 0]} />
              <Bar dataKey="max" name="Max (ms)" fill="#312e81" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* System Info */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Server className="h-5 w-5 text-indigo-600" />
          System Details
        </h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-gray-500 mb-1">Agent ID</p>
            <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 truncate">{callData.agent_id}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Call ID</p>
            <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 truncate">{callData.call_id}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Start Time</p>
            <p className="text-gray-700">{formatTimestamp(callData.start_timestamp)}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Duration</p>
            <p className="text-gray-700">{formatDuration(callData.duration_ms)}</p>
          </div>
        </div>
      </div>

    </div>
  )

  const DebugView = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <h4 className="font-semibold text-gray-900 mb-2">Collected Variables</h4>
          <pre className="text-xs bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto h-64 custom-scrollbar">
            {JSON.stringify(callData.collected_dynamic_variables || {}, null, 2)}
          </pre>
        </div>
        <div>
          <h4 className="font-semibold text-gray-900 mb-2">Metadata</h4>
          <pre className="text-xs bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto h-64 custom-scrollbar">
            {JSON.stringify(callData.metadata || {}, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  )

  return (
    <div className="space-y-6">
      {/* Navigation Tabs */}
      <div className="flex border-b border-gray-200">
        <button
          onClick={() => setActiveTab('overview')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === 'overview'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
        >
          Overview
        </button>
        <button
          onClick={() => setActiveTab('transcript')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === 'transcript'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
        >
          Transcript
        </button>
        <button
          onClick={() => setActiveTab('debug')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === 'debug'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
        >
          Debug Data
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
          {/* Detailed Word-Level Timing could go here if needed, specifically for deeply debugging timing */}
        </div>
      )}

      {activeTab === 'debug' && <DebugView />}
    </div>
  )
}
