import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { apiClient } from '../lib/api'
import { ArrowLeft, Clock, CheckCircle, XCircle, Loader, BarChart3, Phone, Brain, HelpCircle, Sparkles, AudioWaveform, MessageSquare, Download } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'
import Button from '../components/Button'
import RetellCallDetails from '../components/call-recordings/RetellCallDetails'
import VapiCallDetails from '../components/call-recordings/VapiCallDetails'

// Comprehensive metric information with descriptions and ideal values
const METRIC_INFO: Record<string, { 
  description: string
  ideal: string
  unit?: string
  category: 'acoustic' | 'ai_voice' | 'llm'
}> = {
  // Acoustic Metrics (Parselmouth)
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
  
  // AI Voice Quality Metrics
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
  
  // LLM Conversation Metrics
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

const isAudioMetric = (metricName: string): boolean => {
  const info = METRIC_INFO[metricName]
  return info?.category === 'acoustic' || info?.category === 'ai_voice'
}

const getMetricInfo = (metricName: string) => METRIC_INFO[metricName]

// Keep backward compatibility
const getAudioMetricInfo = (metricName: string) => {
  const info = METRIC_INFO[metricName]
  if (!info) return undefined
  return { unit: info.unit || '', description: info.description }
}

// Tooltip component for metrics
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
          {/* Arrow pointing down */}
          <div className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[6px] border-t-gray-900" />
        </div>
      )}
    </div>
  )
}

interface EvaluatorResultDetail {
  id: string
  result_id: string
  name: string
  timestamp: string
  duration_seconds: number | null
  status: 'queued' | 'transcribing' | 'evaluating' | 'completed' | 'failed' | 'call_initiating' | 'call_connecting' | 'call_in_progress' | 'call_ended' | 'fetching_details'
  audio_s3_key: string | null
  transcription: string | null
  speaker_segments?: Array<{
    speaker: string
    text: string
    start: number
    end: number
  }> | null
  metric_scores: Record<string, { value: any; type: string; metric_name: string }> | null
  error_message: string | null
  call_event?: string | null
  provider_call_id?: string | null
  provider_platform?: string | null
  call_data?: any | null
  agent?: {
    id: string
    name: string
    phone_number: string | null
    call_medium?: string
    description: string | null
  }
  persona?: {
    id: string
    name: string
    language: string
    accent: string
    gender: string
    background_noise: string
  }
  scenario?: {
    id: string
    name: string
    description: string | null
    required_info: any
  }
  evaluator?: {
    id: string
    evaluator_id: string
    name: string
  }
}

export default function EvaluatorResultDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const location = window.location.pathname
  const isFromPlayground = location.includes('/playground/test-agent-results')
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioDuration, setAudioDuration] = useState(0)
  const [activeSegmentIndex, setActiveSegmentIndex] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState<'overview' | 'transcript'>('overview')
  const audioRef = useRef<HTMLAudioElement>(null)

  const { data: result, isLoading, error } = useQuery({
    queryKey: ['evaluator-result', id],
    queryFn: () => apiClient.getEvaluatorResult(id!),
    enabled: !!id,
  })

  const { data: presignedUrl } = useQuery({
    queryKey: ['audio-presigned-url', result?.audio_s3_key],
    queryFn: () => {
      if (!result?.audio_s3_key) return null
      return apiClient.getAudioPresignedUrl(result.audio_s3_key)
    },
    enabled: !!result?.audio_s3_key,
  })

  // Load audio URL - prefer provider's recording_url, fallback to S3 presigned URL
  useEffect(() => {
    // First try recording_url from call_data (Retell/Vapi provides this)
    const providerRecordingUrl = result?.call_data?.recording_url
    if (providerRecordingUrl) {
      setAudioUrl(providerRecordingUrl)
      return
    }
    
    // Fallback to S3 presigned URL
    if (presignedUrl?.url) {
      setAudioUrl(presignedUrl.url)
    }
  }, [presignedUrl, result?.call_data])

  // Update audio duration when loaded
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !audioUrl) return

    const handleLoadedMetadata = () => {
      if (audio.duration && audio.duration !== Infinity) {
        setAudioDuration(audio.duration)
      }
    }

    const handleTimeUpdate = () => {
      // Find active segment based on current time
      if (result && 'speaker_segments' in result) {
        const resultData = result as EvaluatorResultDetail
        if (resultData.speaker_segments) {
          const activeIndex = resultData.speaker_segments.findIndex(
            (seg) => audio.currentTime >= seg.start && audio.currentTime <= seg.end
          )
          setActiveSegmentIndex(activeIndex >= 0 ? activeIndex : null)
        }
      }
    }

    audio.addEventListener('loadedmetadata', handleLoadedMetadata)
    audio.addEventListener('timeupdate', handleTimeUpdate)
    
    return () => {
      audio.removeEventListener('loadedmetadata', handleLoadedMetadata)
      audio.removeEventListener('timeupdate', handleTimeUpdate)
    }
  }, [result, audioUrl])

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const handleSegmentClick = (startTime: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = startTime
      audioRef.current.play()
    }
  }

  const formatDuration = (seconds: number | null): string => {
    if (!seconds) return 'N/A'
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }
  
  // Get duration from multiple sources (call_data takes precedence)
  const getEffectiveDuration = (): number | null => {
    // First try call_data.duration_ms
    if (result?.call_data?.duration_ms) {
      return result.call_data.duration_ms / 1000
    }
    // Then try audioDuration from audio element
    if (audioDuration && audioDuration > 0) {
      return audioDuration
    }
    // Finally use duration_seconds from result
    return result?.duration_seconds ?? null
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-5 h-5 text-green-500" />
      case 'failed':
        return <XCircle className="w-5 h-5 text-red-500" />
      case 'queued':
        return <Clock className="w-5 h-5 text-gray-500" />
      case 'transcribing':
      case 'evaluating':
      case 'call_initiating':
      case 'call_connecting':
      case 'call_in_progress':
      case 'fetching_details':
        return <Loader className="w-5 h-5 text-blue-500 animate-spin" />
      case 'call_ended':
        return <Phone className="w-5 h-5 text-emerald-500" />
      default:
        return null
    }
  }

  const getStatusBadge = (status: string) => {
    const baseClasses = "px-3 py-1 text-sm font-medium rounded-full"
    switch (status) {
      case 'completed':
        return `${baseClasses} bg-green-100 text-green-800`
      case 'failed':
        return `${baseClasses} bg-red-100 text-red-800`
      case 'queued':
        return `${baseClasses} bg-gray-100 text-gray-800`
      case 'transcribing':
        return `${baseClasses} bg-blue-100 text-blue-800`
      case 'evaluating':
        return `${baseClasses} bg-purple-100 text-purple-800`
      case 'call_initiating':
        return `${baseClasses} bg-yellow-100 text-yellow-800`
      case 'call_connecting':
        return `${baseClasses} bg-orange-100 text-orange-800`
      case 'call_in_progress':
        return `${baseClasses} bg-cyan-100 text-cyan-800`
      case 'call_ended':
        return `${baseClasses} bg-emerald-100 text-emerald-800`
      case 'fetching_details':
        return `${baseClasses} bg-indigo-100 text-indigo-800`
      default:
        return `${baseClasses} bg-gray-100 text-gray-800`
    }
  }

  const formatMetricValue = (value: any, type: string, metricName?: string): React.ReactNode => {
    if (value === null || value === undefined) return <span className="text-gray-400">N/A</span>
    
    // Normalize type to lowercase for consistent comparison
    const normalizedType = type?.toLowerCase()
    
    // Handle Emotion Category - categorical text values with styling
    if (metricName === 'Emotion Category') {
      const emotion = String(value).toLowerCase()
      const emotionConfig: Record<string, { emoji: string; color: string; bg: string }> = {
        'neutral': { emoji: '😐', color: 'text-gray-700', bg: 'bg-gray-100' },
        'happy': { emoji: '😊', color: 'text-green-700', bg: 'bg-green-100' },
        'sad': { emoji: '😢', color: 'text-blue-700', bg: 'bg-blue-100' },
        'angry': { emoji: '😠', color: 'text-red-700', bg: 'bg-red-100' },
        'fearful': { emoji: '😨', color: 'text-purple-700', bg: 'bg-purple-100' },
        'fear': { emoji: '😨', color: 'text-purple-700', bg: 'bg-purple-100' },
        'surprised': { emoji: '😲', color: 'text-yellow-700', bg: 'bg-yellow-100' },
        'surprise': { emoji: '😲', color: 'text-yellow-700', bg: 'bg-yellow-100' },
        'disgusted': { emoji: '🤢', color: 'text-green-800', bg: 'bg-green-200' },
        'disgust': { emoji: '🤢', color: 'text-green-800', bg: 'bg-green-200' },
        'calm': { emoji: '😌', color: 'text-teal-700', bg: 'bg-teal-100' },
      }
      const config = emotionConfig[emotion] || { emoji: '🎭', color: 'text-gray-700', bg: 'bg-gray-100' }
      
      return (
        <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full ${config.bg}`}>
          <span className="text-xl">{config.emoji}</span>
          <span className={`font-semibold capitalize ${config.color}`}>{value}</span>
        </div>
      )
    }
    
    // Handle boolean metrics
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
    
    // Handle rating metrics with progress bar
    if (normalizedType === 'rating') {
      // Check if value is a string (categorical) rather than a number
      if (typeof value === 'string' && isNaN(parseFloat(value))) {
        // Display as a styled text badge for categorical ratings
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
            <div 
              className={`h-full rounded-full transition-all ${getBarColor(percentage)}`}
              style={{ width: `${percentage}%` }}
            />
          </div>
        </div>
      )
    }
    
    // Handle number metrics (including audio metrics)
    if (normalizedType === 'number') {
      const numValue = typeof value === 'number' ? value : parseFloat(value)
      if (isNaN(numValue)) return <span className="text-gray-400">N/A</span>
      
      // Check if this is an audio metric and add the appropriate unit
      if (metricName && isAudioMetric(metricName)) {
        const audioInfo = getAudioMetricInfo(metricName)
        return (
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold text-gray-900">{numValue.toFixed(2)}</span>
            <span className="text-sm font-medium text-violet-600">{audioInfo?.unit}</span>
          </div>
        )
      }
      
      return <span className="text-2xl font-bold text-gray-900">{numValue.toFixed(1)}</span>
    }
    
    return <span className="text-2xl font-bold text-gray-900">{String(value)}</span>
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    )
  }

  if (error || !result) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">Error loading evaluator result: {error?.message || 'Result not found'}</p>
          <Button onClick={() => navigate('/results')} className="mt-4">
            Back to Results
          </Button>
        </div>
      </div>
    )
  }

  // At this point, we know result exists (checked above)
  const resultData = result as EvaluatorResultDetail

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-6">
        <Button
          onClick={() => navigate(isFromPlayground ? '/playground' : '/results')}
          variant="outline"
          className="mb-4"
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back to {isFromPlayground ? 'Playground' : 'Results'}
        </Button>
        
        <div className="bg-white shadow rounded-lg p-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Test Agent Call Details</h1>
              <p className="text-sm text-gray-500 mt-1">
                Call ID: <span className="font-mono">{resultData.result_id}</span>
              </p>
            </div>
            <div className="flex items-center space-x-3">
              {getStatusIcon(resultData.status)}
              <span className={getStatusBadge(resultData.status)}>
                {resultData.status.toUpperCase().replace('_', ' ')}
              </span>
            </div>
          </div>

          {/* Metadata */}
          <div className="mt-6 grid grid-cols-2 md:grid-cols-5 gap-4">
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Status</p>
              <span
                className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                  resultData.status === 'completed'
                    ? 'bg-green-100 text-green-800'
                    : resultData.status === 'failed'
                    ? 'bg-red-100 text-red-800'
                    : 'bg-yellow-100 text-yellow-800'
                }`}
              >
                {resultData.status}
              </span>
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Agent</p>
              <p className="text-sm text-gray-900">{resultData.agent?.name || 'N/A'}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Duration</p>
              <p className="text-sm text-gray-900 flex items-center">
                <Clock className="w-4 h-4 mr-1" />
                {formatDuration(getEffectiveDuration())}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Created</p>
              <p className="text-sm text-gray-900">
                {resultData.timestamp
                  ? new Date(resultData.timestamp).toLocaleString()
                  : 'N/A'}
              </p>
            </div>
            {resultData.persona && (
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Persona</p>
                <p className="text-sm text-gray-900">{resultData.persona.name}</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Error Message */}
      {resultData.error_message && (
        <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800 font-semibold">Error:</p>
          <p className="text-red-700 mt-1">{resultData.error_message}</p>
        </div>
      )}

      {/* Evaluation Metrics - Top Section */}
      <div className="mb-6 bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold text-gray-900 flex items-center mb-4">
          <BarChart3 className="w-5 h-5 mr-2" />
          Evaluation Metrics
        </h2>
        
        {/* Show loading state when evaluation is in progress */}
        {(resultData.status === 'evaluating' || resultData.status === 'transcribing' || resultData.status === 'queued') && (
          <div className="flex items-center justify-center py-8">
            <Loader className="w-6 h-6 text-blue-500 animate-spin mr-3" />
            <span className="text-gray-600">
              {resultData.status === 'transcribing' ? 'Transcribing audio...' : 
               resultData.status === 'queued' ? 'Evaluation queued...' : 'Evaluating conversation...'}
            </span>
          </div>
        )}
        
        {/* Show error state */}
        {resultData.status === 'failed' && !resultData.metric_scores && (
          <div className="text-center py-8 text-gray-500">
            Evaluation failed. No metrics available.
          </div>
        )}
        
        {/* Show metrics when completed */}
        {resultData.metric_scores && Object.keys(resultData.metric_scores).length > 0 &&
          /* Separate Acoustic, AI Voice, and LLM metrics */
          (() => {
            // Helper to check if a metric has a valid value (not null, undefined, empty, or "N/A")
            const hasValidValue = (metric: { value: any }) => {
              const val = metric.value
              if (val === null || val === undefined) return false
              if (val === '') return false
              if (typeof val === 'string' && val.toLowerCase() === 'n/a') return false
              if (typeof val === 'string' && val.toLowerCase() === 'na') return false
              if (typeof val === 'string' && val.trim() === '') return false
              return true
            }
            
            // Categorize metrics - only include those with valid values
            const acousticMetrics = Object.entries(resultData.metric_scores).filter(
              ([, metric]) => {
                if (!hasValidValue(metric)) return false
                const info = getMetricInfo(metric.metric_name || '')
                return info?.category === 'acoustic'
              }
            )
            const aiVoiceMetrics = Object.entries(resultData.metric_scores).filter(
              ([, metric]) => {
                if (!hasValidValue(metric)) return false
                const info = getMetricInfo(metric.metric_name || '')
                return info?.category === 'ai_voice'
              }
            )
            const llmMetrics = Object.entries(resultData.metric_scores).filter(
              ([, metric]) => {
                if (!hasValidValue(metric)) return false
                const info = getMetricInfo(metric.metric_name || '')
                return !info || info.category === 'llm'
              }
            )
            
            return (
              <div className="space-y-6">
                {/* AI Voice Quality Metrics */}
                {aiVoiceMetrics.length > 0 && (
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <Sparkles className="w-4 h-4 text-purple-600" />
                      <h3 className="text-sm font-semibold text-purple-800 uppercase tracking-wide">AI Voice Quality</h3>
                      <span className="px-2 py-0.5 text-xs bg-purple-100 text-purple-700 rounded-full">ML Analysis</span>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      {aiVoiceMetrics.map(([metricId, metric]) => (
                        <div key={metricId} className="border border-purple-200 bg-purple-50/50 rounded-lg p-4">
                          <div className="text-sm font-medium text-purple-700 mb-2 flex items-center">
                            <span>{metric.metric_name || metricId}</span>
                            <MetricTooltip metricName={metric.metric_name || metricId} />
                          </div>
                          <div>
                            {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                
                {/* Acoustic Metrics (Parselmouth) */}
                {acousticMetrics.length > 0 && (
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <AudioWaveform className="w-4 h-4 text-violet-600" />
                      <h3 className="text-sm font-semibold text-violet-800 uppercase tracking-wide">Acoustic Metrics</h3>
                      <span className="px-2 py-0.5 text-xs bg-violet-100 text-violet-700 rounded-full">Signal Analysis</span>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      {acousticMetrics.map(([metricId, metric]) => (
                        <div key={metricId} className="border border-violet-200 bg-violet-50/50 rounded-lg p-4">
                          <div className="text-sm font-medium text-violet-700 mb-2 flex items-center">
                            <span>{metric.metric_name || metricId}</span>
                            <MetricTooltip metricName={metric.metric_name || metricId} />
                          </div>
                          <div>
                            {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                
                {/* LLM-based Metrics */}
                {llmMetrics.length > 0 && (
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <Brain className="w-4 h-4 text-emerald-600" />
                      <h3 className="text-sm font-semibold text-emerald-800 uppercase tracking-wide">Conversation Metrics</h3>
                      <span className="px-2 py-0.5 text-xs bg-emerald-100 text-emerald-700 rounded-full">LLM Evaluation</span>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                      {llmMetrics.map(([metricId, metric]) => (
                        <div key={metricId} className="border border-gray-200 rounded-lg p-4">
                          <div className="text-sm font-medium text-gray-500 mb-2 flex items-center">
                            <span>{metric.metric_name || metricId}</span>
                            <MetricTooltip metricName={metric.metric_name || metricId} />
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
            )
          })()}
        
        {/* Show message when no metrics and completed */}
        {resultData.status === 'completed' && (!resultData.metric_scores || Object.keys(resultData.metric_scores).length === 0) && (
          <div className="text-center py-8 text-gray-500">
            No evaluation metrics available.
          </div>
        )}
      </div>

      {/* Call Data from Provider (Retell/Vapi) - Show this prominently when available */}
      {/* Show RetellCallDetails for Retell calls */}
      {resultData.call_data && (resultData.provider_platform === 'retell' || resultData.call_data.call_id?.startsWith('call_')) && (
        <div className="mb-6 bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center mb-4">
            <Phone className="w-5 h-5 mr-2" />
            Call Details 
            <span className="ml-2 px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded-full capitalize">
              retell
            </span>
            {(resultData.provider_call_id || resultData.call_data.call_id) && (
              <span className="ml-2 text-xs text-gray-500 font-mono">
                {resultData.provider_call_id || resultData.call_data.call_id}
              </span>
            )}
          </h2>
          <RetellCallDetails callData={resultData.call_data} />
        </div>
      )}

      {/* Show VapiCallDetails for Vapi calls */}
      {resultData.call_data && resultData.provider_platform === 'vapi' && (
        <div className="mb-6 bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center mb-4">
            <Phone className="w-5 h-5 mr-2" />
            Call Details 
            <span className="ml-2 px-2 py-0.5 text-xs bg-violet-100 text-violet-800 rounded-full capitalize">
              vapi
            </span>
            {(resultData.provider_call_id || resultData.call_data.call_id) && (
              <span className="ml-2 text-xs text-gray-500 font-mono">
                {resultData.provider_call_id || resultData.call_data.call_id}
              </span>
            )}
          </h2>
          <VapiCallDetails callData={resultData.call_data} />
        </div>
      )}

      {/* Unknown provider - show raw JSON */}
      {resultData.call_data && resultData.provider_platform && resultData.provider_platform !== 'retell' && resultData.provider_platform !== 'vapi' && (
        <div className="mb-6 bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center mb-4">
            <Phone className="w-5 h-5 mr-2" />
            Call Details 
            <span className="ml-2 px-2 py-0.5 text-xs bg-gray-100 text-gray-800 rounded-full capitalize">
              {resultData.provider_platform}
            </span>
          </h2>
          <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-xs max-h-96">
            {JSON.stringify(resultData.call_data, null, 2)}
          </pre>
        </div>
      )}

      {/* Call Details - Audio Recording and Transcription (Test Agents only - no provider call_data) */}
      {!resultData.call_data && (resultData.audio_s3_key || resultData.transcription || resultData.speaker_segments) && (
      <div className="bg-white shadow rounded-lg p-6">
        {/* Navigation Tabs - matching RetellCallDetails style */}
        <div className="flex border-b border-gray-200 mb-6">
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

        {/* Overview Tab */}
        {activeTab === 'overview' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left Column - Transcript Card (2 cols) */}
            <div className="lg:col-span-2">
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col h-[600px]">
                <div className="flex items-center justify-between mb-4 flex-shrink-0">
                  <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                    <MessageSquare className="h-5 w-5 text-indigo-600" />
                    Transcript
                  </h3>
                  {audioUrl && (
                    <div className="flex items-center gap-2 bg-gray-100 rounded-full px-3 py-1">
                      <audio controls src={audioUrl} className="h-8 w-64" />
                      <a href={audioUrl} download className="text-gray-500 hover:text-indigo-600 p-1">
                        <Download className="h-4 w-4" />
                      </a>
                    </div>
                  )}
                </div>

                <div className="flex-1 overflow-y-auto space-y-4 pr-2">
                  {resultData.speaker_segments && resultData.speaker_segments.length > 0 ? (
                    resultData.speaker_segments.map((segment, index) => {
                      const isUser = segment.speaker === 'Speaker 1'
                      const isActive = activeSegmentIndex === index
                      
                      return (
                        <div 
                          key={index} 
                          className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
                          onClick={() => handleSegmentClick(segment.start)}
                        >
                          <div className={`max-w-[80%] rounded-2xl px-4 py-3 cursor-pointer transition-all ${
                            isUser
                              ? 'bg-indigo-600 text-white rounded-br-none'
                              : 'bg-gray-100 text-gray-800 rounded-bl-none'
                          } ${isActive ? 'ring-2 ring-indigo-400 shadow-lg' : ''}`}>
                            <div className="flex items-center gap-2 mb-1 opacity-80">
                              <span className="text-xs font-semibold uppercase tracking-wider">
                                {isUser ? 'Test Agent (Caller)' : (resultData.agent?.name || 'Voice AI Agent')}
                              </span>
                              <span className="text-[10px]">
                                {formatTime(segment.start)}
                              </span>
                            </div>
                            <p className="text-sm leading-relaxed whitespace-pre-wrap">{segment.text}</p>
                          </div>
                        </div>
                      )
                    })
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
            </div>

            {/* Right Column - Call Info (1 col) */}
            <div className="lg:col-span-1 space-y-6">
              {/* Call Summary Card */}
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                  <Phone className="h-5 w-5 text-indigo-600" />
                  Call Summary
                </h3>
                <div className="space-y-4">
                  <div className="p-4 bg-gray-50 rounded-lg">
                    <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Duration</p>
                    <p className="text-lg font-semibold text-gray-900">{formatDuration(getEffectiveDuration())}</p>
                  </div>
                  
                  <div className="p-4 bg-gray-50 rounded-lg">
                    <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Status</p>
                    <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                      resultData.status === 'completed'
                        ? 'bg-green-100 text-green-800'
                        : resultData.status === 'failed'
                        ? 'bg-red-100 text-red-800'
                        : 'bg-yellow-100 text-yellow-800'
                    }`}>
                      {resultData.status}
                    </span>
                  </div>

                  {resultData.agent && (
                    <div className="p-4 bg-gray-50 rounded-lg">
                      <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1">Agent</p>
                      <p className="text-sm font-medium text-gray-900">{resultData.agent.name}</p>
                      {resultData.agent.description && (
                        <p className="text-xs text-gray-500 mt-1 line-clamp-3">{resultData.agent.description}</p>
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
            </div>
          </div>
        )}

        {/* Transcript Tab - Full Width */}
        {activeTab === 'transcript' && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col h-[700px]">
            <div className="flex items-center justify-between mb-4 flex-shrink-0">
              <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                <MessageSquare className="h-5 w-5 text-indigo-600" />
                Full Transcript
              </h3>
              {audioUrl && (
                <div className="flex items-center gap-2 bg-gray-100 rounded-full px-3 py-1">
                  <audio controls src={audioUrl} className="h-8 w-64" />
                  <a href={audioUrl} download className="text-gray-500 hover:text-indigo-600 p-1">
                    <Download className="h-4 w-4" />
                  </a>
                </div>
              )}
            </div>

            <div className="flex-1 overflow-y-auto space-y-4 pr-2">
              {resultData.speaker_segments && resultData.speaker_segments.length > 0 ? (
                resultData.speaker_segments.map((segment, index) => {
                  const isUser = segment.speaker === 'Speaker 1'
                  const isActive = activeSegmentIndex === index
                  
                  return (
                    <div 
                      key={index} 
                      className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
                      onClick={() => handleSegmentClick(segment.start)}
                    >
                      <div className={`max-w-[70%] rounded-2xl px-4 py-3 cursor-pointer transition-all ${
                        isUser
                          ? 'bg-indigo-600 text-white rounded-br-none'
                          : 'bg-gray-100 text-gray-800 rounded-bl-none'
                      } ${isActive ? 'ring-2 ring-indigo-400 shadow-lg' : ''}`}>
                        <div className="flex items-center gap-2 mb-1 opacity-80">
                          <span className="text-xs font-semibold uppercase tracking-wider">
                            {isUser ? 'Test Agent (Caller)' : (resultData.agent?.name || 'Voice AI Agent')}
                          </span>
                          <span className="text-[10px]">
                            {formatTime(segment.start)}
                          </span>
                        </div>
                        <p className="text-sm leading-relaxed whitespace-pre-wrap">{segment.text}</p>
                      </div>
                    </div>
                  )
                })
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
        )}

        {/* Hidden audio element for programmatic control (segment click navigation) */}
        <audio
          ref={audioRef}
          src={audioUrl || ''}
          preload="metadata"
          onEnded={() => setActiveSegmentIndex(null)}
          onLoadedMetadata={() => {
            if (audioRef.current?.duration && audioRef.current.duration !== Infinity) {
              setAudioDuration(audioRef.current.duration)
            }
          }}
          className="hidden"
        />
      </div>
      )}
    </div>
  )
}

