import { useState } from 'react'
import {
  Clock, MessageSquare, TrendingUp, Download, Server, BarChart3, CheckCircle, XCircle, HelpCircle, Brain, Sparkles, AudioWaveform
} from 'lucide-react'

// Metric information for tooltips and categorization
const METRIC_INFO: Record<string, { 
  description: string
  ideal: string
  unit?: string
  category: 'acoustic' | 'ai_voice' | 'llm'
}> = {
  'Pitch Variance': { 
    description: 'F0 variation measuring prosodic expressiveness.',
    ideal: '20-50 Hz (natural speech)',
    unit: 'Hz',
    category: 'acoustic'
  },
  'Jitter': { 
    description: 'Cycle-to-cycle pitch period variation.',
    ideal: '< 1% (healthy voice)',
    unit: '%',
    category: 'acoustic'
  },
  'Shimmer': { 
    description: 'Amplitude perturbation measuring voice quality.',
    ideal: '< 3% (clear voice)',
    unit: '%',
    category: 'acoustic'
  },
  'HNR': { 
    description: 'Harmonics-to-Noise Ratio measuring signal clarity.',
    ideal: '> 20 dB (clear voice)',
    unit: 'dB',
    category: 'acoustic'
  },
  'MOS Score': { 
    description: 'Mean Opinion Score (1-5 scale).',
    ideal: '4.0+ (studio quality)',
    category: 'ai_voice'
  },
  'Emotion Confidence': { 
    description: 'Confidence score for detected emotion.',
    ideal: '> 0.7 (high confidence)',
    category: 'ai_voice'
  },
  'Valence': { 
    description: 'Emotional positivity/negativity scale.',
    ideal: '-1.0 to +1.0',
    category: 'ai_voice'
  },
  'Arousal': { 
    description: 'Emotional intensity/energy level.',
    ideal: '0.3-0.6 (engaged)',
    category: 'ai_voice'
  },
  'Prosody Score': { 
    description: 'Expressiveness/drama score.',
    ideal: '0.4-0.7 (natural)',
    category: 'ai_voice'
  },
  'Follow Instructions': { 
    description: 'How well the agent followed instructions.',
    ideal: '> 0.8 (80%+)',
    category: 'llm'
  },
  'Problem Resolution': { 
    description: 'Whether the agent resolved the problem.',
    ideal: 'true',
    category: 'llm'
  },
  'Professionalism': { 
    description: 'Professional demeanor and language.',
    ideal: '> 0.85 (85%+)',
    category: 'llm'
  },
  'Clarity and Empathy': { 
    description: 'Clear communication with empathy.',
    ideal: '> 0.8 (80%+)',
    category: 'llm'
  },
}

const getMetricInfo = (metricName: string) => METRIC_INFO[metricName] || null

interface TestVoiceAgentResultData {
  id?: string
  result_id?: string
  name?: string
  timestamp?: string
  duration_seconds?: number | null
  status?: 'queued' | 'transcribing' | 'evaluating' | 'completed' | 'failed'
  transcription?: string | null
  speaker_segments?: Array<{
    speaker: string
    text: string
    start: number
    end: number
  }> | null
  metric_scores?: Record<string, { value: any; type: string; metric_name: string }> | null
  call_analysis?: {
    call_summary?: string
    user_sentiment?: string
    call_successful?: boolean
  }
  audio_s3_key?: string | null
  audioUrl?: string
  agent?: {
    id?: string
    name?: string
    description?: string
  }
  persona?: {
    name?: string
  }
  scenario?: {
    name?: string
  }
}

interface TestVoiceAgentResultDetailsProps {
  resultData: TestVoiceAgentResultData
}

export default function TestVoiceAgentResultDetails({ resultData }: TestVoiceAgentResultDetailsProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'transcript' | 'debug'>('overview')

  const formatDuration = (seconds?: number | null) => {
    if (!seconds) return 'N/A'
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}m ${secs}s`
  }

  const formatTimestamp = (timestamp?: string) => {
    if (!timestamp) return 'N/A'
    return new Date(timestamp).toLocaleString()
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const getSentimentColor = (sentiment?: string) => {
    if (!sentiment) return 'text-gray-500 bg-gray-100'
    const s = sentiment.toLowerCase()
    if (s.includes('positive') || s.includes('happy')) return 'text-green-700 bg-green-100'
    if (s.includes('negative') || s.includes('angry')) return 'text-red-700 bg-red-100'
    return 'text-blue-700 bg-blue-100'
  }

  // Extract summary, sentiment, and successful from metric_scores or call_analysis
  const summary = resultData.call_analysis?.call_summary || 
    (resultData.metric_scores?.summary?.value) || 
    null
  
  const sentiment = resultData.call_analysis?.user_sentiment || 
    (resultData.metric_scores?.sentiment?.value) || 
    'Neutral'
  
  const successful = resultData.call_analysis?.call_successful !== undefined 
    ? resultData.call_analysis.call_successful 
    : (resultData.metric_scores?.successful?.value !== undefined 
        ? resultData.metric_scores.successful.value 
        : null)

  // Map speaker labels - Speaker 1 is typically the Test Agent (caller), Speaker 2 is Voice AI Agent
  const getSpeakerLabel = (speaker: string) => {
    if (speaker === 'Speaker 1' || speaker === 'user' || speaker === 'caller') {
      return 'Test Agent'
    }
    return resultData.agent?.name || 'Voice AI Agent'
  }

  const isUserSpeaker = (speaker: string) => {
    return speaker === 'Speaker 1' || speaker === 'user' || speaker === 'caller'
  }

  const SummaryCard = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <TrendingUp className="h-5 w-5 text-indigo-600" />
        Call Analysis
      </h3>

      {summary || resultData.call_analysis ? (
        <div className="space-y-6">
          {summary && (
            <div className="p-4 bg-indigo-50 rounded-lg border border-indigo-100">
              <p className="text-sm font-medium text-indigo-900 mb-2">Summary</p>
              <p className="text-sm text-indigo-800 leading-relaxed">{summary}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Sentiment</p>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-1 rounded-full text-xs font-semibold ${getSentimentColor(sentiment)}`}>
                  {sentiment}
                </span>
              </div>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Success Status</p>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-1 rounded-full text-xs font-semibold ${
                  successful === true
                    ? 'text-green-700 bg-green-100'
                    : successful === false
                    ? 'text-red-700 bg-red-100'
                    : 'text-gray-500 bg-gray-100'
                }`}>
                  {successful === true ? 'Successful' : successful === false ? 'Unsuccessful' : 'N/A'}
                </span>
              </div>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Status</p>
              <span className={`px-2 py-1 rounded-full text-xs font-semibold capitalize ${
                resultData.status === 'completed'
                  ? 'text-green-700 bg-green-100'
                  : resultData.status === 'failed'
                  ? 'text-red-700 bg-red-100'
                  : 'text-yellow-700 bg-yellow-100'
              }`}>
                {resultData.status || 'Unknown'}
              </span>
            </div>

            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Duration</p>
              <span className="text-sm font-medium text-gray-900">
                {formatDuration(resultData.duration_seconds)}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="text-center py-8 text-gray-500">Analysis not available</div>
      )}
    </div>
  )

  // Helper function to format metric values
  const formatMetricValue = (value: any, type: string, metricName: string): string => {
    if (value === null || value === undefined) return 'N/A'
    if (type === 'boolean') return value ? 'Yes' : 'No'
    if (type === 'rating') return `${(value * 100).toFixed(0)}%`
    if (typeof value === 'number') {
      const info = getMetricInfo(metricName)
      if (info?.unit) return `${value.toFixed(2)} ${info.unit}`
      return value.toFixed(2)
    }
    return String(value)
  }

  // Helper to check if metric has a valid value
  const hasValidValue = (metric: any): boolean => {
    return metric?.value !== null && metric?.value !== undefined && !metric?.error
  }

  // Helper to get metric icon based on value quality
  const getMetricIcon = (value: any, type: string) => {
    if (value === null || value === undefined) return <HelpCircle className="w-4 h-4 text-gray-400" />
    if (type === 'boolean') return value ? <CheckCircle className="w-4 h-4 text-green-500" /> : <XCircle className="w-4 h-4 text-red-500" />
    if (type === 'rating') {
      if (value >= 0.8) return <CheckCircle className="w-4 h-4 text-green-500" />
      if (value >= 0.6) return <HelpCircle className="w-4 h-4 text-yellow-500" />
      return <XCircle className="w-4 h-4 text-red-500" />
    }
    return null
  }

  const MetricsCard = () => {
    if (!resultData.metric_scores || Object.keys(resultData.metric_scores).length === 0) {
      return null
    }

    // Categorize metrics
    const metrics = Object.entries(resultData.metric_scores)
    const llmMetrics = metrics.filter(([, m]) => {
      if (!hasValidValue(m)) return false
      const info = getMetricInfo(m.metric_name)
      return !info || info.category === 'llm'
    })
    const acousticMetrics = metrics.filter(([, m]) => {
      if (!hasValidValue(m)) return false
      const info = getMetricInfo(m.metric_name)
      return info?.category === 'acoustic'
    })
    const aiVoiceMetrics = metrics.filter(([, m]) => {
      if (!hasValidValue(m)) return false
      const info = getMetricInfo(m.metric_name)
      return info?.category === 'ai_voice'
    })

    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-indigo-600" />
          Evaluation Metrics
        </h3>
        
        <div className="space-y-6">
          {/* LLM Conversation Metrics */}
          {llmMetrics.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Brain className="w-4 h-4 text-blue-600" />
                <h4 className="text-sm font-semibold text-blue-800 uppercase tracking-wide">Conversation Quality</h4>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {llmMetrics.map(([id, metric]) => (
                  <div key={id} className="p-3 bg-blue-50 rounded-lg border border-blue-100">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-xs text-blue-700 font-medium truncate">{metric.metric_name}</p>
                      {getMetricIcon(metric.value, metric.type)}
                    </div>
                    <p className="text-lg font-bold text-blue-900">
                      {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* AI Voice Quality Metrics */}
          {aiVoiceMetrics.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="w-4 h-4 text-purple-600" />
                <h4 className="text-sm font-semibold text-purple-800 uppercase tracking-wide">AI Voice Quality</h4>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {aiVoiceMetrics.map(([id, metric]) => (
                  <div key={id} className="p-3 bg-purple-50 rounded-lg border border-purple-100">
                    <p className="text-xs text-purple-700 font-medium truncate mb-1">{metric.metric_name}</p>
                    <p className="text-lg font-bold text-purple-900">
                      {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                    </p>
                    {getMetricInfo(metric.metric_name)?.ideal && (
                      <p className="text-[10px] text-purple-600 mt-1">
                        Ideal: {getMetricInfo(metric.metric_name)?.ideal}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Acoustic Metrics */}
          {acousticMetrics.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <AudioWaveform className="w-4 h-4 text-green-600" />
                <h4 className="text-sm font-semibold text-green-800 uppercase tracking-wide">Acoustic Analysis</h4>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {acousticMetrics.map(([id, metric]) => (
                  <div key={id} className="p-3 bg-green-50 rounded-lg border border-green-100">
                    <p className="text-xs text-green-700 font-medium truncate mb-1">{metric.metric_name}</p>
                    <p className="text-lg font-bold text-green-900">
                      {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                    </p>
                    {getMetricInfo(metric.metric_name)?.ideal && (
                      <p className="text-[10px] text-green-600 mt-1">
                        Ideal: {getMetricInfo(metric.metric_name)?.ideal}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  const TranscriptCard = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col h-[600px]">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-indigo-600" />
          Transcript
        </h3>
        {resultData.audioUrl && (
          <div className="flex items-center gap-2 bg-gray-100 rounded-full px-3 py-1">
            <audio controls src={resultData.audioUrl} className="h-8 w-64" />
            <a href={resultData.audioUrl} download className="text-gray-500 hover:text-indigo-600 p-1">
              <Download className="h-4 w-4" />
            </a>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pr-2 custom-scrollbar">
        {resultData.speaker_segments && resultData.speaker_segments.length > 0 ? (
          resultData.speaker_segments.map((segment, idx) => (
            <div key={idx} className={`flex ${isUserSpeaker(segment.speaker) ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                isUserSpeaker(segment.speaker)
                  ? 'bg-indigo-600 text-white rounded-br-none'
                  : 'bg-gray-100 text-gray-800 rounded-bl-none'
              }`}>
                <div className="flex items-center gap-2 mb-1 opacity-80">
                  <span className="text-xs font-semibold uppercase tracking-wider">
                    {getSpeakerLabel(segment.speaker)}
                  </span>
                  <span className="text-[10px]">
                    {formatTime(segment.start)}
                  </span>
                </div>
                <p className="text-sm leading-relaxed whitespace-pre-wrap">{segment.text}</p>
              </div>
            </div>
          ))
        ) : resultData.transcription ? (
          <div className="prose max-w-none">
            <p className="text-gray-700 whitespace-pre-wrap text-sm">{resultData.transcription}</p>
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">
            {resultData.status === 'transcribing' ? 'Transcription in progress...' : 'No transcript available'}
          </div>
        )}
      </div>
    </div>
  )

  const StatsParams = () => (
    <div className="space-y-6">
      {/* Call Info Card */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Clock className="h-5 w-5 text-indigo-600" />
          Call Information
        </h3>
        <div className="space-y-4">
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Duration</p>
            <p className="text-2xl font-bold text-gray-900">
              {formatDuration(resultData.duration_seconds)}
            </p>
          </div>
          
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Timestamp</p>
            <p className="text-sm font-medium text-gray-900">
              {formatTimestamp(resultData.timestamp)}
            </p>
          </div>

          {resultData.agent && (
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Agent</p>
              <p className="text-sm font-medium text-gray-900">{resultData.agent.name}</p>
              {resultData.agent.description && (
                <p className="text-xs text-gray-500 mt-1 line-clamp-2">{resultData.agent.description}</p>
              )}
            </div>
          )}

          {resultData.persona && (
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Persona</p>
              <p className="text-sm font-medium text-gray-900">{resultData.persona.name}</p>
            </div>
          )}

          {resultData.scenario && (
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Scenario</p>
              <p className="text-sm font-medium text-gray-900">{resultData.scenario.name}</p>
            </div>
          )}
        </div>
      </div>

      {/* System Info */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Server className="h-5 w-5 text-indigo-600" />
          System Details
        </h3>
        <div className="grid grid-cols-1 gap-4 text-sm">
          <div>
            <p className="text-gray-500 mb-1">Result ID</p>
            <p className="font-mono bg-gray-50 p-2 rounded text-gray-700 truncate">{resultData.result_id || resultData.id}</p>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Status</p>
            <p className={`inline-flex px-2 py-1 rounded-full text-xs font-semibold capitalize ${
              resultData.status === 'completed'
                ? 'text-green-700 bg-green-100'
                : resultData.status === 'failed'
                ? 'text-red-700 bg-red-100'
                : 'text-yellow-700 bg-yellow-100'
            }`}>
              {resultData.status || 'Unknown'}
            </p>
          </div>
          {resultData.audio_s3_key && (
            <div>
              <p className="text-gray-500 mb-1">Audio Storage</p>
              <p className="font-mono bg-gray-50 p-2 rounded text-gray-700 text-xs truncate">{resultData.audio_s3_key}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )

  const DebugView = () => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <h4 className="font-semibold text-gray-900 mb-2">Metric Scores</h4>
          <pre className="text-xs bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto h-64 custom-scrollbar">
            {JSON.stringify(resultData.metric_scores || {}, null, 2)}
          </pre>
        </div>
        <div>
          <h4 className="font-semibold text-gray-900 mb-2">Full Result Data</h4>
          <pre className="text-xs bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto h-64 custom-scrollbar">
            {JSON.stringify({
              id: resultData.id,
              result_id: resultData.result_id,
              status: resultData.status,
              duration_seconds: resultData.duration_seconds,
              audio_s3_key: resultData.audio_s3_key,
              agent: resultData.agent,
              persona: resultData.persona,
              scenario: resultData.scenario,
            }, null, 2)}
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
        <div className="space-y-6">
          {/* Evaluation Metrics - Full Width at Top */}
          <MetricsCard />
          
          {/* Main Content Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-6">
              <SummaryCard />
              <TranscriptCard />
            </div>
            <div className="lg:col-span-1">
              <StatsParams />
            </div>
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
