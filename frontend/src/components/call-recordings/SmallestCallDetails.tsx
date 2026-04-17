import { useMemo, useState } from 'react'
import {
  DollarSign, MessageSquare, TrendingUp, Download, Activity, Server, CheckCircle, XCircle
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend
} from 'recharts'

interface SmallestTranscriptEntry {
  speaker: string
  text: string
  start?: number
  end?: number
}

interface SmallestCallData {
  call_id?: string
  call_status?: string
  start_timestamp?: string
  end_timestamp?: string
  duration_seconds?: number
  transcript?: string
  transcript_object?: SmallestTranscriptEntry[]
  recording_url?: string
  analysis?: {
    summary?: string
    latency_stats?: Record<string, any>
    interruption_count?: number
    cost?: number
  }
  agent_id?: string
  raw_data?: Record<string, any>
}

interface SmallestCallDetailsProps {
  callData: SmallestCallData
  hideTranscript?: boolean
}

const COLORS = ['#10b981', '#06b6d4', '#f59e0b', '#8b5cf6']

const labelize = (value: string) =>
  value.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]/g, ' ').replace(/\s+/g, ' ').trim()

const toNumber = (value: any): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

export default function SmallestCallDetails({ callData, hideTranscript = false }: SmallestCallDetailsProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'transcript'>('overview')

  const rawData = callData.raw_data || {}
  const transcriptEntries = callData.transcript_object || []
  const recordingUrl = callData.recording_url || rawData.recordingUrl
  const status = (callData.call_status || rawData.status || '').toString().toLowerCase()
  const callFailureReason = rawData.callFailureReason || rawData.hangupCause || ''
  const isSuccessful = status === 'ended' && !callFailureReason
  const summary = callData.analysis?.summary || rawData.summary || ''
  const language = rawData.agent?.language?.default || 'N/A'
  const endedReason = callFailureReason || rawData.endReason || callData.call_status || 'Normal'

  const interruptionCount = useMemo(() => {
    if (typeof callData.analysis?.interruption_count === 'number') {
      return callData.analysis.interruption_count
    }
    const events = Array.isArray(rawData.events) ? rawData.events : []
    return events.filter((event: any) =>
      String(event?.eventType || '').toLowerCase().includes('interrupt')
    ).length
  }, [callData.analysis?.interruption_count, rawData.events])

  const totalCredits = useMemo(() => {
    const rawCost = rawData.callCost
    if (typeof rawCost === 'number') return rawCost
    if (typeof rawCost === 'object' && rawCost) {
      return (
        toNumber(rawCost.total) ||
        toNumber(rawCost.totalCredits) ||
        (toNumber(rawCost.callCharge) || 0) + (toNumber(rawCost.llmCharge) || 0)
      )
    }
    return callData.analysis?.cost || 0
  }, [callData.analysis?.cost, rawData.callCost])

  const costData = useMemo(() => {
    const rawCost = rawData.callCost
    if (typeof rawCost === 'object' && rawCost) {
      const items = [
        { name: 'Call', value: toNumber(rawCost.callCharge) || toNumber(rawCost.call) || 0 },
        { name: 'LLM', value: toNumber(rawCost.llmCharge) || toNumber(rawCost.llm) || 0 },
      ].filter(item => item.value > 0)
      if (items.length > 0) return items
    }
    return totalCredits > 0 ? [{ name: 'Total', value: totalCredits }] : []
  }, [rawData.callCost, totalCredits])

  const latencyData = useMemo(() => {
    const latencyStats = callData.analysis?.latency_stats || rawData.latencyStats || {}
    return Object.entries(latencyStats)
      .map(([key, value]) => ({ name: labelize(key), value: toNumber(value) }))
      .filter((entry): entry is { name: string; value: number } => entry.value !== undefined)
      .slice(0, 8)
  }, [callData.analysis?.latency_stats, rawData.latencyStats])

  const formatDuration = (seconds?: number) => {
    if (!seconds || seconds <= 0) return 'N/A'
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = Math.floor(seconds % 60)
    return `${minutes}m ${remainingSeconds}s`
  }

  const formatTimestamp = (timestamp?: string) => {
    if (!timestamp) return 'N/A'
    const dt = new Date(timestamp)
    return Number.isNaN(dt.getTime()) ? timestamp : dt.toLocaleString()
  }

  const SummaryCard = () => (
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
        <div className="grid grid-cols-2 gap-4">
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Success</p>
            {isSuccessful ? (
              <span className="flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold text-green-700 bg-green-100 w-fit">
                <CheckCircle className="h-3 w-3" />
                Successful
              </span>
            ) : (
              <span className="flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold text-red-700 bg-red-100 w-fit">
                <XCircle className="h-3 w-3" />
                Unsuccessful
              </span>
            )}
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Interruptions</p>
            <span className="text-lg font-bold text-gray-900">{interruptionCount}</span>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Ended Reason</p>
            <span className="text-sm font-medium text-gray-900">{String(endedReason)}</span>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Language</p>
            <span className="text-sm font-medium text-gray-900 uppercase">{language}</span>
          </div>
        </div>
      </div>
    </div>
  )

  const TranscriptCard = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col h-[600px]">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-emerald-600" />
          Transcript
        </h3>
        {recordingUrl && (
          <div className="flex items-center gap-2 bg-gray-100 rounded-full px-3 py-1">
            <audio controls src={recordingUrl} className="h-8 w-64" />
            <a href={recordingUrl} download className="text-gray-500 hover:text-emerald-600 p-1">
              <Download className="h-4 w-4" />
            </a>
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto space-y-4 pr-2 custom-scrollbar">
        {transcriptEntries.length > 0 ? (
          transcriptEntries.map((entry, idx) => {
            const speaker = String(entry.speaker || '').toLowerCase()
            const isUser = speaker === 'user' || speaker === 'customer' || speaker === 'caller' || speaker === 'human'
            return (
              <div key={idx} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${isUser
                  ? 'bg-emerald-600 text-white rounded-br-none'
                  : 'bg-gray-100 text-gray-800 rounded-bl-none'
                  }`}>
                  <div className="flex items-center gap-2 mb-1 opacity-80">
                    <span className="text-xs font-semibold uppercase tracking-wider">
                      {isUser ? 'User' : 'Agent'}
                    </span>
                    {typeof entry.start === 'number' && entry.start > 0 && (
                      <span className="text-[10px]">{entry.start.toFixed(1)}s</span>
                    )}
                  </div>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{entry.text}</p>
                </div>
              </div>
            )
          })
        ) : callData.transcript ? (
          <div className="p-4 bg-gray-50 rounded-lg">
            <pre className="text-sm whitespace-pre-wrap text-gray-800 font-sans">{callData.transcript}</pre>
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">No transcript available</div>
        )}
      </div>
    </div>
  )

  const StatsParams = () => (
    <div className="space-y-6">
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <DollarSign className="h-5 w-5 text-emerald-600" />
          Cost Breakdown
        </h3>
        <div className="flex items-center justify-between">
          <div className="w-1/2">
            <p className="text-sm text-gray-500">Total Cost</p>
            <p className="text-3xl font-bold text-gray-900">
              {Math.round(totalCredits).toLocaleString()} <span className="text-sm font-normal text-gray-500">credits</span>
            </p>
            <p className="text-xs text-gray-500 mt-1">Duration: {formatDuration(callData.duration_seconds)}</p>
            {costData.length > 1 && (
              <div className="space-y-2 mt-3">
                {costData.map((item) => (
                  <div key={item.name} className="flex justify-between items-center text-sm">
                    <span className="text-gray-600">{item.name}</span>
                    <span className="font-medium text-gray-900">{Math.round(item.value).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="w-1/2 h-40">
            {costData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={costData} cx="50%" cy="50%" outerRadius={60} dataKey="value">
                    {costData.map((_entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value: number) => `${Math.round(value).toLocaleString()} credits`} />
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
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="value" name="Latency" fill="#10b981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">Latency data not available</div>
        )}
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Server className="h-5 w-5 text-emerald-600" />
          System Details
        </h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-gray-500 mb-1">Call ID</p>
            <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 truncate text-xs">{callData.call_id}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Agent ID</p>
            <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 truncate text-xs">{callData.agent_id || rawData.agent?._id || 'N/A'}</p>
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
            <p className="text-gray-700 capitalize">{callData.call_status || rawData.status || 'unknown'}</p>
          </div>
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
