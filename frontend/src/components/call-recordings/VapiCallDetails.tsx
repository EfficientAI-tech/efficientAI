import { useState } from 'react'
import {
    DollarSign, MessageSquare, Server, Activity
} from 'lucide-react'
import {
    PieChart, Pie, Cell, ResponsiveContainer, Tooltip
} from 'recharts'

interface VapiMessage {
    role: string
    message?: string
    content?: string // Sometimes it's content, sometimes message
    time?: number
    secondsFromStart?: number
}

interface VapiCallData {
    call_id?: string
    call_status?: string
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
        [key: string]: number | undefined
    }
    transcript?: string
    messages?: VapiMessage[]
    analysis?: {
        summary?: string
        structuredData?: any
        successEvaluation?: string
        latency_stats?: {
            p50?: number
            p90?: number
            p95?: number
            p99?: number
            max?: number
            min?: number
            avg?: number
            num_turns?: number
        }
        interruption_count?: number
    }
    monitor?: any
    ended_reason?: string
    raw_data?: any
}

interface VapiCallDetailsProps {
    callData: VapiCallData
}

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8'];

export default function VapiCallDetails({ callData }: VapiCallDetailsProps) {
    const [activeTab, setActiveTab] = useState<'overview' | 'transcript' | 'debug'>('overview')

    const formatDuration = (seconds?: number) => {
        if (!seconds) return 'N/A'
        const mins = Math.floor(seconds / 60)
        const secs = Math.floor(seconds % 60)
        return `${mins}m ${secs}s`
    }

    const formatTimestamp = (timestamp?: string) => {
        if (!timestamp) return 'N/A'
        return new Date(timestamp).toLocaleString()
    }

    const getMessageContent = (msg: VapiMessage) => msg.message || msg.content || ''

    // Prepare Cost Data
    const costData = callData.cost_breakdown ? Object.entries(callData.cost_breakdown)
        .filter(([KEY, value]) => value && value > 0 && KEY !== 'total')
        .map(([key, value]) => ({
            name: key.toUpperCase(),
            value: value
        })) : []

    const SummaryCard = () => (
        <>
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                    <Activity className="h-5 w-5 text-indigo-600" />
                    Call Analysis
                </h3>

                {callData.analysis ? (
                    <div className="space-y-6">
                        <div className="p-4 bg-indigo-50 rounded-lg border border-indigo-100">
                            <p className="text-sm font-medium text-indigo-900 mb-2">Summary</p>
                            <p className="text-sm text-indigo-800 leading-relaxed">
                                {callData.analysis.summary || "No summary provided."}
                            </p>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            {callData.analysis.successEvaluation && (
                                <div className="p-4 bg-gray-50 rounded-lg">
                                    <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Success Evaluation</p>
                                    <p className="text-sm text-gray-800">{String(callData.analysis.successEvaluation)}</p>
                                </div>
                            )}
                            {callData.ended_reason && (
                                <div className="p-4 bg-gray-50 rounded-lg">
                                    <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Ended Reason</p>
                                    <p className="text-sm text-gray-800 capitalize">{callData.ended_reason}</p>
                                </div>
                            )}
                            {callData.analysis.interruption_count !== undefined && (
                                <div className="p-4 bg-red-50 rounded-lg">
                                    <p className="text-xs text-red-500 uppercase tracking-wider font-semibold mb-1">User Interruptions</p>
                                    <p className="text-xl font-bold text-red-800">{callData.analysis.interruption_count}</p>
                                </div>
                            )}
                        </div>

                        {callData.analysis.latency_stats && (
                            <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                                <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
                                    <p className="text-xs font-semibold text-gray-700 uppercase tracking-wider">Latency Stats (ms)</p>
                                </div>
                                <div className="grid grid-cols-4 divide-x divide-gray-100">
                                    <div className="p-3 text-center">
                                        <p className="text-xs text-gray-500">P50</p>
                                        <p className="text-sm font-bold text-gray-900">{callData.analysis.latency_stats.p50}</p>
                                    </div>
                                    <div className="p-3 text-center">
                                        <p className="text-xs text-gray-500">P90</p>
                                        <p className="text-sm font-bold text-gray-900">{callData.analysis.latency_stats.p90}</p>
                                    </div>
                                    <div className="p-3 text-center">
                                        <p className="text-xs text-gray-500">P95</p>
                                        <p className="text-sm font-bold text-gray-900">{callData.analysis.latency_stats.p95}</p>
                                    </div>
                                    <div className="p-3 text-center">
                                        <p className="text-xs text-gray-500">Avg</p>
                                        <p className="text-sm font-bold text-gray-900">{callData.analysis.latency_stats.avg}</p>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                ) : (
                    <div className="text-center py-8 text-gray-500">Analysis not available yet</div>
                )}
            </div>
        </>
    )

    const TranscriptCard = () => (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col h-[600px]">
            <div className="flex items-center justify-between mb-4 flex-shrink-0">
                <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                    <MessageSquare className="h-5 w-5 text-indigo-600" />
                    Transcript
                </h3>
            </div>

            <div className="flex-1 overflow-y-auto space-y-4 pr-2 custom-scrollbar">
                {callData.messages && callData.messages.length > 0 ? (
                    callData.messages.map((msg, idx) => (
                        <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                            <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${msg.role === 'user'
                                ? 'bg-indigo-600 text-white rounded-br-none'
                                : 'bg-gray-100 text-gray-800 rounded-bl-none'
                                }`}>
                                <div className="flex items-center gap-2 mb-1 opacity-80">
                                    <span className="text-xs font-semibold uppercase tracking-wider">
                                        {msg.role === 'user' ? 'User' : 'Agent'}
                                    </span>
                                    {(msg.secondsFromStart !== undefined || msg.time !== undefined) && (
                                        <span className="text-[10px]">
                                            {((msg.secondsFromStart || msg.time || 0) / 1000).toFixed(1)}s
                                        </span>
                                    )}
                                </div>
                                <p className="text-sm leading-relaxed whitespace-pre-wrap">{getMessageContent(msg)}</p>
                            </div>
                        </div>
                    ))
                ) : callData.transcript ? (
                    <p className="whitespace-pre-wrap text-sm text-gray-700 leading-relaxed font-mono bg-gray-50 p-4 rounded-lg">
                        {callData.transcript}
                    </p>
                ) : (
                    <p className="text-gray-400 italic text-center text-sm py-10">No transcript available</p>
                )}
            </div>
        </div>
    )

    const StatsCard = () => (
        <div className="space-y-6">
            {/* Cost Card */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                    <DollarSign className="h-5 w-5 text-indigo-600" />
                    Cost Breakdown
                </h3>

                <div className="flex flex-col gap-4">
                    <div>
                        <p className="text-sm text-gray-500">Total Cost</p>
                        <p className="text-3xl font-bold text-gray-900">
                            ${callData.cost?.toFixed(4) || '0.0000'}
                        </p>
                        <p className="text-xs text-gray-500 mt-1">
                            Duration: {callData.duration_seconds?.toFixed(1) || 0}s
                        </p>
                    </div>

                    {callData.cost_breakdown && costData.length > 0 ? (
                        <div className="flex items-center justify-between">
                            <div className="space-y-2 w-1/2">
                                {costData.map((item, i) => (
                                    <div key={i} className="flex justify-between items-center text-xs">
                                        <div className="flex items-center gap-2">
                                            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }}></div>
                                            <span className="text-gray-600 capitalize">{item.name}</span>
                                        </div>
                                        <span className="font-medium text-gray-900">${Number(item.value).toFixed(4)}</span>
                                    </div>
                                ))}
                            </div>
                            <div className="w-1/2 h-32">
                                <ResponsiveContainer width="100%" height="100%">
                                    <PieChart>
                                        <Pie
                                            data={costData}
                                            cx="50%"
                                            cy="50%"
                                            innerRadius={25}
                                            outerRadius={40}
                                            paddingAngle={5}
                                            dataKey="value"
                                        >
                                            {costData.map((_, index) => (
                                                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                            ))}
                                        </Pie>
                                        <Tooltip formatter={(value: number) => `$${value.toFixed(4)}`} />
                                    </PieChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    ) : (
                        <p className="text-xs text-gray-500 italic">Detailed cost breakdown not available</p>
                    )}
                </div>
            </div>

            {/* Latency / Monitor Info */}
            {callData.monitor && (
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                        <Activity className="h-5 w-5 text-indigo-600" />
                        Performance
                    </h3>
                    <pre className="text-xs bg-gray-50 text-gray-700 p-2 rounded overflow-x-auto custom-scrollbar max-h-48">
                        {JSON.stringify(callData.monitor, null, 2)}
                    </pre>
                </div>
            )}

            {/* System Info */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                    <Server className="h-5 w-5 text-indigo-600" />
                    System Details
                </h3>
                <div className="grid grid-cols-1 gap-4 text-sm">
                    <div>
                        <p className="text-gray-500 mb-1">Call ID</p>
                        <p className="font-mono bg-gray-50 p-1 rounded text-gray-700 truncate text-xs">{callData.call_id}</p>
                    </div>
                    <div>
                        <p className="text-gray-500 mb-1">Status</p>
                        <p className="text-gray-700 capitalize">{callData.call_status}</p>
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
                        <p className="text-gray-700 text-xs">{formatDuration(callData.duration_seconds)}</p>
                    </div>
                </div>
            </div>
        </div>
    )

    const DebugView = () => (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h4 className="font-semibold text-gray-900 mb-2">Raw Data</h4>
            <pre className="text-xs bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto h-96 custom-scrollbar">
                {JSON.stringify(callData.raw_data || callData, null, 2)}
            </pre>
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
                        <StatsCard />
                    </div>
                </div>
            )}

            {activeTab === 'transcript' && (
                <div className="space-y-6">
                    <TranscriptCard />
                </div>
            )}

            {activeTab === 'debug' && <DebugView />}
        </div>
    )
}
