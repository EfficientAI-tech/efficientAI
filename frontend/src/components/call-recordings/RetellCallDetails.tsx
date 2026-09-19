import { useState } from 'react'
import {
  DollarSign, MessageSquare, TrendingUp, Download, Activity, Server
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts'
import { formatMessageTiming } from '../../lib/callTranscriptTiming'
import { transcriptBubbleClass, transcriptMetaClass } from './transcriptBubbleStyles'

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

export type RetellDetailSection = 'full' | 'transcript' | 'cost' | 'latency' | 'analysis' | 'system'

interface RetellCallDetailsProps {
  callData: RetellCallData
  hideTranscript?: boolean
  section?: RetellDetailSection
  compact?: boolean
  embedded?: boolean
  evaluatorAnalysis?: {
    call_summary?: string
    user_sentiment?: string
    call_successful?: boolean
  } | null
}

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8'];

export default function RetellCallDetails({
  callData,
  hideTranscript = false,
  section = 'full',
  compact = false,
  embedded = false,
  evaluatorAnalysis = null,
}: RetellCallDetailsProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'transcript'>('overview')

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
    value: item.cost / 100,
  })) || []

  const mergedAnalysis = callData.call_analysis || (evaluatorAnalysis
    ? {
        call_summary: evaluatorAnalysis.call_summary,
        user_sentiment: evaluatorAnalysis.user_sentiment,
        call_successful: evaluatorAnalysis.call_successful,
      }
    : undefined)
  const usingEvaluatorSummary = !callData.call_analysis && !!evaluatorAnalysis?.call_summary
  const publicLogUrl = (callData as any).public_log_url as string | undefined

  const SummaryCard = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <TrendingUp className="h-5 w-5 text-indigo-600" />
        Call Analysis
      </h3>

      {mergedAnalysis ? (
        <div className="space-y-6">
          {usingEvaluatorSummary && (
            <p className="text-xs text-gray-500">
              Retell post-call analysis is still pending — showing EfficientAI-generated summary from the evaluation.
            </p>
          )}
          <div className="p-4 bg-indigo-50 rounded-lg border border-indigo-100">
            <p className="text-sm font-medium text-indigo-900 mb-2">Summary</p>
            <p className="text-sm text-indigo-800 leading-relaxed">
              {mergedAnalysis.call_summary || "No summary available."}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Sentiment</p>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-1 rounded-full text-xs font-semibold ${getSentimentColor(mergedAnalysis.user_sentiment)}`}>
                  {mergedAnalysis.user_sentiment || 'Neutral'}
                </span>
              </div>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Success Status</p>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-1 rounded-full text-xs font-semibold ${mergedAnalysis.call_successful
                  ? 'text-green-700 bg-green-100'
                  : 'text-yellow-700 bg-yellow-100'
                  }`}>
                  {mergedAnalysis.call_successful ? 'Successful' : 'Unsuccessful'}
                </span>
              </div>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Voicemail</p>
              <span className="text-sm font-medium text-gray-900">
                {callData.call_analysis?.in_voicemail ? 'Yes' : 'No'}
              </span>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Ended Reason</p>
              <span className="text-sm font-medium text-gray-900 capitalize">
                {callData.disconnection_reason?.replace(/_/g, ' ') || 'Normal'}
              </span>
            </div>
          </div>

          {publicLogUrl && (
            <a
              href={publicLogUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex text-sm text-indigo-600 hover:text-indigo-800"
            >
              Open Retell call log
            </a>
          )}
        </div>
      ) : (
        <div className="text-center py-8 text-gray-500">
          Analysis not available yet. Use Sync provider data after the call ends.
        </div>
      )}
    </div>
  )

  const TranscriptCard = () => {
    const flat = compact || embedded
    return (
    <div
      className={
        flat
          ? 'space-y-3'
          : 'flex h-[600px] flex-col rounded-xl border border-gray-200 bg-white p-6 shadow-sm'
      }
    >
      {!flat ? (
      <div className="mb-4 flex flex-shrink-0 items-center justify-between">
        <h3 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
          <MessageSquare className="h-5 w-5 text-indigo-600" />
          Transcript
        </h3>
        {callData.recording_url && (
          <div className="flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1">
            <audio controls src={callData.recording_url} className="h-8 w-64" />
            <a href={callData.recording_url} download className="p-1 text-gray-500 hover:text-indigo-600">
              <Download className="h-4 w-4" />
            </a>
          </div>
        )}
      </div>
      ) : null}

      <div className={flat ? 'space-y-3' : 'custom-scrollbar flex-1 space-y-4 overflow-y-auto pr-2'}>
        {callData.transcript_object?.map((msg, idx) => {
          const isUser = msg.role === 'user'
          return (
          <div key={idx} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
            <div className={transcriptBubbleClass(isUser, '80')}>
              <div className={`${transcriptMetaClass(isUser)} opacity-90`}>
                <span>{isUser ? 'User' : (callData.agent_name || 'Agent')}</span>
                {msg.words && msg.words.length > 0 ? (
                  <span className="font-normal normal-case tracking-normal tabular-nums">
                    {formatMessageTiming(msg.words[0].start, msg.words[msg.words.length - 1].end)}
                  </span>
                ) : null}
              </div>
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>
            </div>
          </div>
        )})}
      </div>
    </div>
    )
  }

  const CostSection = () => (
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
                ${((callData.call_cost?.combined_cost ?? 0) / 100).toFixed(4)}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                Duration: {callData.call_cost?.total_duration_seconds}s
              </p>
            </div>
            <div className="space-y-2">
              {callData.call_cost?.product_costs?.map((prod, i) => (
                <div key={i} className="flex justify-between items-center text-sm">
                  <span className="text-gray-600 capitalize">{prod.product.replace(/_/g, ' ')}</span>
                  <span className="font-medium text-gray-900">${(prod.cost / 100).toFixed(4)}</span>
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
                  <Tooltip formatter={(value: number) => `$${value.toFixed(4)}`} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
  )

  const LatencySection = () => (
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
  )

  const SystemSection = () => (
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
  )

  const StatsParams = () => (
    <div className="space-y-6">
      <CostSection />
      <LatencySection />
      <SystemSection />
    </div>
  )

  if (section === 'transcript') return <TranscriptCard />
  if (section === 'cost') return <CostSection />
  if (section === 'latency') return <LatencySection />
  if (section === 'analysis') return <SummaryCard />
  if (section === 'system') return <SystemSection />

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
