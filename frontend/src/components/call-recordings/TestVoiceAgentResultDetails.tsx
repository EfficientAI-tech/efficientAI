import { useState, type ReactNode } from 'react'
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
    description: 'F0 variation measuring prosodic expressiveness. Higher values indicate more expressive speech.',
    ideal: '20-50 Hz (natural speech)',
    unit: 'Hz',
    category: 'acoustic'
  },
  'Jitter': { 
    description: 'Cycle-to-cycle pitch period variation indicating vocal stability. Lower is better.',
    ideal: '< 1% (healthy voice)',
    unit: '%',
    category: 'acoustic'
  },
  'Shimmer': { 
    description: 'Amplitude perturbation measuring voice quality consistency. Lower is better.',
    ideal: '< 3% (clear voice)',
    unit: '%',
    category: 'acoustic'
  },
  'HNR': { 
    description: 'Harmonics-to-Noise Ratio measuring signal clarity. Higher indicates cleaner voice.',
    ideal: '> 20 dB (clear, non-breathy)',
    unit: 'dB',
    category: 'acoustic'
  },
  'MOS Score': { 
    description: 'Mean Opinion Score predicting human perception of audio quality (1-5 scale).',
    ideal: '4.0+ (studio quality), 3.0 (phone quality), <2.0 (poor/robotic)',
    category: 'ai_voice'
  },
  'Emotion Category': {
    description: 'Dominant emotion detected in the voice (angry, happy, sad, neutral, fearful, etc.).',
    ideal: 'Depends on context - should match expected tone',
    category: 'ai_voice'
  },
  'Emotion Confidence': { 
    description: 'Confidence score for the detected emotion category.',
    ideal: '> 0.7 (high confidence)',
    category: 'ai_voice'
  },
  'Valence': { 
    description: 'Emotional positivity/negativity scale. Negative = sad/angry, Positive = happy/excited.',
    ideal: '-1.0 to +1.0 (context dependent)',
    category: 'ai_voice'
  },
  'Arousal': { 
    description: 'Emotional intensity/energy level. Low = calm/sleepy, High = excited/energetic.',
    ideal: '0.3-0.6 (engaged but not agitated)',
    category: 'ai_voice'
  },
  'Speaker Consistency': {
    description: 'Voice identity stability throughout the call. Detects if voice changed mid-call (glitch).',
    ideal: '> 0.8 (same voice), < 0.5 indicates voice glitch',
    category: 'ai_voice'
  },
  'Prosody Score': { 
    description: 'Expressiveness/drama score. Low = monotone/flat, High = expressive/dynamic.',
    ideal: '0.4-0.7 (natural expressiveness)',
    category: 'ai_voice'
  },
  'Follow Instructions': { 
    description: 'How well the agent followed the given instructions and guidelines.',
    ideal: '> 0.8 (80%+)',
    category: 'llm'
  },
  'Problem Resolution': { 
    description: 'Whether the agent successfully resolved the customer\'s problem or query.',
    ideal: '> 0.8 (80%+)',
    category: 'llm'
  },
  'Professionalism': { 
    description: 'Professional demeanor, appropriate language, and courteous behavior.',
    ideal: '> 0.85 (85%+)',
    category: 'llm'
  },
  'Clarity and Empathy': { 
    description: 'Clear communication combined with understanding and acknowledgment of customer feelings.',
    ideal: '> 0.8 (80%+)',
    category: 'llm'
  },
  'Objective Achieved': {
    description: 'Whether the conversation\'s primary objective was successfully achieved.',
    ideal: 'Yes/True',
    category: 'llm'
  },
  'Overall Quality': {
    description: 'Holistic assessment of the entire conversation quality.',
    ideal: '> 0.8 (80%+)',
    category: 'llm'
  },
}

const getMetricInfo = (metricName: string) => METRIC_INFO[metricName] || null

const SECTION_INFO: Record<'conversation' | 'ai_voice' | 'acoustic', string> = {
  conversation: 'LLM-based evaluation of how well the agent handled intent, instructions, and resolution quality.',
  ai_voice: 'ML-based voice quality metrics on naturalness, affect, consistency, and expressiveness.',
  acoustic: 'Signal-level acoustic measurements from the recording (pitch stability, perturbation, noise ratio).',
}

const MetricTooltip = ({ metricName }: { metricName: string }) => {
  const [isVisible, setIsVisible] = useState(false)
  const info = getMetricInfo(metricName)

  if (!info) return null

  return (
    <div className="relative inline-block ml-1">
      <button
        type="button"
        className="text-gray-400 hover:text-gray-600 focus:outline-none transition-colors"
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        onClick={() => setIsVisible(!isVisible)}
        aria-label={`Info about ${metricName}`}
      >
        <HelpCircle className="w-3.5 h-3.5" />
      </button>
      {isVisible && (
        <div className="absolute z-50 left-1/2 -translate-x-1/2 bottom-full mb-2 w-64 p-3 text-xs bg-gray-900 text-white rounded-lg shadow-xl pointer-events-none">
          <div className="font-semibold text-gray-100 mb-1.5">{metricName}</div>
          <p className="text-gray-300 mb-2 leading-relaxed">{info.description}</p>
          <div className="flex items-center gap-1 pt-1.5 border-t border-gray-700">
            <span className="text-emerald-400 font-medium">Ideal:</span>
            <span className="text-gray-200">{info.ideal}</span>
          </div>
          <div className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[6px] border-t-gray-900" />
        </div>
      )}
    </div>
  )
}

const SectionTooltip = ({ section }: { section: 'conversation' | 'ai_voice' | 'acoustic' }) => {
  const [isVisible, setIsVisible] = useState(false)

  return (
    <div className="relative inline-block">
      <button
        type="button"
        className="text-gray-400 hover:text-gray-600 focus:outline-none transition-colors"
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        onClick={() => setIsVisible(!isVisible)}
        aria-label={`Info about ${section} metrics`}
      >
        <HelpCircle className="w-3.5 h-3.5" />
      </button>
      {isVisible && (
        <div className="absolute z-50 left-1/2 -translate-x-1/2 bottom-full mb-2 w-72 p-3 text-xs bg-gray-900 text-white rounded-lg shadow-xl pointer-events-none">
          <p className="text-gray-200 leading-relaxed">{SECTION_INFO[section]}</p>
          <div className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[6px] border-t-gray-900" />
        </div>
      )}
    </div>
  )
}

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
  metric_scores?: Record<
    string,
    {
      value: any
      type: string
      metric_name: string
      skipped?: string
      error?: string | null
    }
  > | null
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

  const getSpeakerLabel = (speaker: string) => {
    if (speaker === 'Speaker 1' || speaker === 'user' || speaker === 'caller') {
      return 'You'
    }
    if (speaker === 'assistant' || speaker === 'Speaker 2' || speaker === 'bot') {
      return resultData.agent?.name || 'Agent'
    }
    return resultData.agent?.name || 'Agent'
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
  const formatMetricValue = (value: any, type: string, metricName: string): ReactNode => {
    if (value === null || value === undefined) return <span className="text-gray-400">N/A</span>

    const normalizedType = type?.toLowerCase()

    if (metricName === 'Emotion Category') {
      const emotion = String(value).toLowerCase()
      const emotionConfig: Record<string, { emoji: string; color: string; bg: string }> = {
        neutral: { emoji: '😐', color: 'text-gray-700', bg: 'bg-gray-100' },
        happy: { emoji: '😊', color: 'text-green-700', bg: 'bg-green-100' },
        sad: { emoji: '😢', color: 'text-blue-700', bg: 'bg-blue-100' },
        angry: { emoji: '😠', color: 'text-red-700', bg: 'bg-red-100' },
        fearful: { emoji: '😨', color: 'text-purple-700', bg: 'bg-purple-100' },
        fear: { emoji: '😨', color: 'text-purple-700', bg: 'bg-purple-100' },
        surprised: { emoji: '😲', color: 'text-yellow-700', bg: 'bg-yellow-100' },
        surprise: { emoji: '😲', color: 'text-yellow-700', bg: 'bg-yellow-100' },
        disgusted: { emoji: '🤢', color: 'text-green-800', bg: 'bg-green-200' },
        disgust: { emoji: '🤢', color: 'text-green-800', bg: 'bg-green-200' },
        calm: { emoji: '😌', color: 'text-teal-700', bg: 'bg-teal-100' },
      }
      const config = emotionConfig[emotion] || { emoji: '🎭', color: 'text-gray-700', bg: 'bg-gray-100' }

      return (
        <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full ${config.bg}`}>
          <span className="text-xl">{config.emoji}</span>
          <span className={`font-semibold capitalize ${config.color}`}>{value}</span>
        </div>
      )
    }

    if (normalizedType === 'boolean') {
      const boolValue = value === true || value === 1 || value === '1' || value === 'true'
      return boolValue ? (
        <div className="flex items-center space-x-1.5 text-green-600">
          <CheckCircle className="w-5 h-5" />
          <span className="font-semibold">Yes</span>
        </div>
      ) : (
        <div className="flex items-center space-x-1.5 text-red-600">
          <XCircle className="w-5 h-5" />
          <span className="font-semibold">No</span>
        </div>
      )
    }

    if (normalizedType === 'rating') {
      if (typeof value === 'string' && isNaN(parseFloat(value))) {
        return (
          <span className="inline-flex items-center px-3 py-1.5 rounded-full bg-purple-100 text-purple-700 font-semibold capitalize">
            {value}
          </span>
        )
      }

      const numValue = typeof value === 'number' ? value : parseFloat(value)
      if (isNaN(numValue)) return <span className="text-gray-400">N/A</span>

      const normalizedValue = Math.max(0, Math.min(1, numValue))
      const percentage = Math.round(normalizedValue * 100)
      const getBarColor = (pct: number): string => {
        if (pct >= 70) return 'bg-green-500'
        if (pct >= 50) return 'bg-yellow-500'
        return 'bg-red-500'
      }

      return (
        <div className="flex flex-col gap-2">
          <span className="text-2xl font-bold text-gray-900">{percentage}%</span>
          <div className="w-full h-3 bg-gray-200 rounded-full overflow-hidden">
            <div className={`h-full rounded-full transition-all ${getBarColor(percentage)}`} style={{ width: `${percentage}%` }} />
          </div>
        </div>
      )
    }

    if (normalizedType === 'number') {
      const numValue = typeof value === 'number' ? value : parseFloat(value)
      if (isNaN(numValue)) return <span className="text-gray-400">N/A</span>

      const info = getMetricInfo(metricName)
      if (info?.category === 'acoustic' || info?.category === 'ai_voice') {
        return (
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold text-gray-900">{numValue.toFixed(2)}</span>
            <span className="text-sm font-medium text-violet-600">{info.unit || ''}</span>
          </div>
        )
      }
      return <span className="text-2xl font-bold text-gray-900">{numValue.toFixed(1)}</span>
    }

    return <span className="text-2xl font-bold text-gray-900">{String(value)}</span>
  }

  // Helper to check if metric has a valid value
  const hasValidValue = (metric: any): boolean => {
    const val = metric?.value
    if (val === null || val === undefined) return false
    if (val === '') return false
    if (typeof val === 'string' && val.toLowerCase() === 'n/a') return false
    if (typeof val === 'string' && val.toLowerCase() === 'na') return false
    if (typeof val === 'string' && val.trim() === '') return false
    return true
  }

  const isAudioCategoryMetric = (metricName?: string): boolean => {
    if (!metricName) return false
    const info = getMetricInfo(metricName)
    return info?.category === 'acoustic' || info?.category === 'ai_voice'
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
    const unavailableAudioMetrics = metrics.filter(([, m]) => {
      if (!isAudioCategoryMetric(m?.metric_name)) return false
      if (m?.skipped === 'audio_required') return true
      if (typeof m?.error === 'string' && m.error.trim().length > 0) return true
      return false
    })
    const hasAnyAudioMetric = metrics.some(([, m]) => isAudioCategoryMetric(m?.metric_name))
    const hasAudioUnavailableNotice = hasAnyAudioMetric && unavailableAudioMetrics.length > 0

    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-indigo-600" />
          Evaluation Metrics
        </h3>
        
        <div className="space-y-6">
          {hasAudioUnavailableNotice && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {unavailableAudioMetrics.length === 1
                ? 'An audio metric is unavailable for this run. Audio analysis could not complete for that metric.'
                : 'Some audio metrics are unavailable for this run. Audio analysis could not fully complete for one or more metrics.'}
            </div>
          )}

          {/* LLM Conversation Metrics */}
          {llmMetrics.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Brain className="w-4 h-4 text-emerald-600" />
                <h4 className="text-sm font-semibold text-emerald-800 uppercase tracking-wide">Conversation Quality</h4>
                <SectionTooltip section="conversation" />
                <span className="px-2 py-0.5 text-xs bg-emerald-100 text-emerald-700 rounded-full">LLM Evaluation</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                {llmMetrics.map(([id, metric]) => (
                  <div key={id} className="border border-gray-200 rounded-lg p-4">
                    <div className="text-sm font-medium text-gray-500 mb-2 flex items-center">
                      <span>{metric.metric_name}</span>
                      <MetricTooltip metricName={metric.metric_name} />
                    </div>
                    <div>
                      {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                    </div>
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
                <SectionTooltip section="ai_voice" />
                <span className="px-2 py-0.5 text-xs bg-purple-100 text-purple-700 rounded-full">ML Analysis</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {aiVoiceMetrics.map(([id, metric]) => (
                  <div key={id} className="border border-purple-200 bg-purple-50/50 rounded-lg p-4">
                    <div className="text-sm font-medium text-purple-700 mb-2 flex items-center">
                      <span>{metric.metric_name}</span>
                      <MetricTooltip metricName={metric.metric_name} />
                    </div>
                    <div>
                      {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Acoustic Metrics */}
          {acousticMetrics.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <AudioWaveform className="w-4 h-4 text-violet-600" />
                <h4 className="text-sm font-semibold text-violet-800 uppercase tracking-wide">Acoustic Analysis</h4>
                <SectionTooltip section="acoustic" />
                <span className="px-2 py-0.5 text-xs bg-violet-100 text-violet-700 rounded-full">Signal Analysis</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {acousticMetrics.map(([id, metric]) => (
                  <div key={id} className="border border-violet-200 bg-violet-50/50 rounded-lg p-4">
                    <div className="text-sm font-medium text-violet-700 mb-2 flex items-center">
                      <span>{metric.metric_name}</span>
                      <MetricTooltip metricName={metric.metric_name} />
                    </div>
                    <div>
                      {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                    </div>
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
