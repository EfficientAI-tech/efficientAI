import { useState, useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart3, HelpCircle, Brain, Sparkles, AudioWaveform
} from 'lucide-react'
import { apiClient } from '../../lib/api'

const LEGACY_CATEGORY_LABEL_METRIC_NAMES = new Set([
  'yes',
  'no',
  'true',
  'false',
  'same',
  'different',
])

function isLegacyCategoryLabelMetric(metric: {
  type?: string | null
  metric_name?: string | null
}): boolean {
  if ((metric.type || '').toLowerCase() !== 'boolean') return false
  const name = (metric.metric_name || '').trim().toLowerCase()
  return LEGACY_CATEGORY_LABEL_METRIC_NAMES.has(name)
}
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
    <div className="relative inline-flex flex-shrink-0 ml-1 mt-0.5">
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
      parent_metric_id?: string | null
      rationale?: string | null
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
  metricsOnly?: boolean
}

export default function TestVoiceAgentResultDetails({
  resultData,
  metricsOnly = false,
}: TestVoiceAgentResultDetailsProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'debug'>('overview')

  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics'],
    queryFn: () => apiClient.listMetrics(),
  })

  const childMetricIds = useMemo(() => {
    const ids = new Set<string>()
    const visit = (metric: { id?: string; parent_metric_id?: string | null; children?: any[] }) => {
      if (metric.parent_metric_id && metric.id) ids.add(metric.id)
      for (const child of metric.children || []) {
        if (child?.id) ids.add(child.id)
        visit(child)
      }
    }
    for (const metric of metrics as Array<{ id?: string; parent_metric_id?: string | null; children?: any[] }>) {
      visit(metric)
    }
    return ids
  }, [metrics])

  const shouldHideMetricScore = (
    metricId: string,
    metric: { parent_metric_id?: string | null; type?: string | null; metric_name?: string | null },
  ) => {
    return Boolean(
      metric.parent_metric_id ||
        childMetricIds.has(metricId) ||
        isLegacyCategoryLabelMetric(metric),
    )
  }

  // Helper function to format metric values
  const formatMetricValue = (value: any, type: string, metricName: string): ReactNode => {
    if (value === null || value === undefined) return <span className="text-gray-400">N/A</span>

    const normalizedType = type?.toLowerCase()

    if (normalizedType === 'category') {
      if (value === '') return <span className="text-gray-400">N/A</span>
      return (
        <span className="inline-flex max-w-full items-center px-3 py-1.5 rounded-lg bg-indigo-50 text-indigo-700 text-sm font-semibold whitespace-normal break-words leading-snug">
          {String(value)}
        </span>
      )
    }

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
      return <span className="block text-base font-semibold text-gray-900">{boolValue ? 'Yes' : 'No'}</span>
    }

    if (normalizedType === 'rating') {
      if (typeof value === 'string' && isNaN(parseFloat(value))) {
        return (
          <span className="inline-flex max-w-full items-center px-3 py-1.5 rounded-full bg-purple-100 text-purple-700 font-semibold capitalize whitespace-normal break-words text-left leading-snug">
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

    return <span className="block max-w-full text-base font-semibold leading-snug text-gray-900 whitespace-normal break-words">{String(value)}</span>
  }

  const renderMetricRationale = (metric: { rationale?: string | null }) => {
    const rationale = typeof metric.rationale === 'string' ? metric.rationale.trim() : ''
    if (!rationale) return null
    return (
      <p className="mt-2 text-xs text-gray-600 leading-relaxed border-t border-gray-100 pt-2">
        {rationale}
      </p>
    )
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
    const llmMetrics = metrics.filter(([id, m]) => {
      if (shouldHideMetricScore(id, m)) return false
      if (!hasValidValue(m)) return false
      const info = getMetricInfo(m.metric_name)
      return !info || info.category === 'llm'
    })
    const acousticMetrics = metrics.filter(([id, m]) => {
      if (shouldHideMetricScore(id, m)) return false
      if (!hasValidValue(m)) return false
      const info = getMetricInfo(m.metric_name)
      return info?.category === 'acoustic'
    })
    const aiVoiceMetrics = metrics.filter(([id, m]) => {
      if (shouldHideMetricScore(id, m)) return false
      if (!hasValidValue(m)) return false
      const info = getMetricInfo(m.metric_name)
      return info?.category === 'ai_voice'
    })
    const unavailableAudioMetrics = metrics.filter(([id, m]) => {
      if (shouldHideMetricScore(id, m)) return false
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
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                {llmMetrics.map(([id, metric]) => (
                  <div key={id} className="min-w-0 border border-gray-200 rounded-lg p-4">
                    <div className="text-xs font-bold uppercase text-gray-700 mb-2 flex min-w-0 items-start gap-1.5">
                      <span className="min-w-0 flex-1 whitespace-normal break-words leading-snug">{metric.metric_name}</span>
                      <MetricTooltip metricName={metric.metric_name} />
                    </div>
                    <div>
                      {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                      {renderMetricRationale(metric)}
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
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
                {aiVoiceMetrics.map(([id, metric]) => (
                  <div key={id} className="min-w-0 border border-purple-200 bg-purple-50/50 rounded-lg p-4">
                    <div className="text-xs font-bold uppercase text-purple-800 mb-2 flex min-w-0 items-start gap-1.5">
                      <span className="min-w-0 flex-1 whitespace-normal break-words leading-snug">{metric.metric_name}</span>
                      <MetricTooltip metricName={metric.metric_name} />
                    </div>
                    <div>
                      {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                      {renderMetricRationale(metric)}
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
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
                {acousticMetrics.map(([id, metric]) => (
                  <div key={id} className="min-w-0 border border-violet-200 bg-violet-50/50 rounded-lg p-4">
                    <div className="text-xs font-bold uppercase text-violet-800 mb-2 flex min-w-0 items-start gap-1.5">
                      <span className="min-w-0 flex-1 whitespace-normal break-words leading-snug">{metric.metric_name}</span>
                      <MetricTooltip metricName={metric.metric_name} />
                    </div>
                    <div>
                      {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                      {renderMetricRationale(metric)}
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
      {metricsOnly ? (
        <MetricsCard />
      ) : (
        <>
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
          onClick={() => setActiveTab('debug')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === 'debug'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          }`}
        >
          Debug Data
        </button>
      </div>

      {activeTab === 'overview' && <MetricsCard />}

      {activeTab === 'debug' && <DebugView />}
        </>
      )}
    </div>
  )
}
