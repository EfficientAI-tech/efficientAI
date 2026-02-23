import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { apiClient } from '../lib/api'
import { ArrowLeft, Clock, CheckCircle, XCircle, Loader, BarChart3, Phone, Brain, HelpCircle, Sparkles, AudioWaveform, MessageSquare, Download, RotateCcw } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
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

const isAudioMetric = (metricName: string): boolean => {
  const info = METRIC_INFO[metricName]
  return info?.category === 'acoustic' || info?.category === 'ai_voice'
}

const getMetricInfo = (metricName: string) => METRIC_INFO[metricName]

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
    <div className="relative inline-block ml-1.5">
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
      
      <AnimatePresence>
        {isVisible && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.15 }}
            className="absolute z-50 left-1/2 -translate-x-1/2 bottom-full mb-2 w-64 p-3 text-xs bg-gray-900 text-white rounded-xl shadow-xl pointer-events-none"
          >
            <div className="font-semibold text-gray-100 mb-1.5">{metricName}</div>
            <p className="text-gray-400 mb-2 leading-relaxed">{info.description}</p>
            <div className="flex items-center gap-1 pt-1.5 border-t border-gray-700">
              <span className="text-emerald-400 font-medium">Ideal:</span>
              <span className="text-gray-300">{info.ideal}</span>
            </div>
            <div className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[6px] border-t-gray-900" />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

interface EvaluatorResultDetail {
  id: string
  result_id: string
  name: string
  evaluator_id: string | null
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

export default function EvaluatorResultDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
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
    refetchInterval: (query) => {
      const data = query.state.data as any
      if (data && ['queued', 'call_initiating', 'call_connecting', 'call_in_progress', 'call_ended', 'transcribing', 'evaluating', 'fetching_details'].includes(data.status)) {
        return 3000
      }
      return false
    },
  })

  const { data: presignedUrl } = useQuery({
    queryKey: ['audio-presigned-url', result?.audio_s3_key],
    queryFn: () => {
      if (!result?.audio_s3_key) return null
      return apiClient.getAudioPresignedUrl(result.audio_s3_key)
    },
    enabled: !!result?.audio_s3_key,
  })

  const reEvaluateMutation = useMutation({
    mutationFn: (resultId: string) => apiClient.reEvaluateResult(resultId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluator-result', id] })
      queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
    },
  })

  useEffect(() => {
    const providerRecordingUrl = result?.call_data?.recording_url
    if (providerRecordingUrl) {
      setAudioUrl(providerRecordingUrl)
      return
    }
    if (presignedUrl?.url) {
      setAudioUrl(presignedUrl.url)
    }
  }, [presignedUrl, result?.call_data])

  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !audioUrl) return

    const handleLoadedMetadata = () => {
      if (audio.duration && audio.duration !== Infinity) {
        setAudioDuration(audio.duration)
      }
    }

    const handleTimeUpdate = () => {
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
    if (!seconds) return '--'
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}m ${secs}s`
  }
  
  const getEffectiveDuration = (): number | null => {
    if (result?.call_data?.duration_ms) {
      return result.call_data.duration_ms / 1000
    }
    if (audioDuration && audioDuration > 0) {
      return audioDuration
    }
    return result?.duration_seconds ?? null
  }

  const getStatusConfig = (status: string) => {
    switch (status) {
      case 'completed':
        return { dot: 'bg-emerald-500', bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200', label: 'Completed', icon: <CheckCircle className="w-4 h-4 text-emerald-500" /> }
      case 'failed':
        return { dot: 'bg-rose-500', bg: 'bg-rose-50', text: 'text-rose-700', border: 'border-rose-200', label: 'Failed', icon: <XCircle className="w-4 h-4 text-rose-500" /> }
      case 'queued':
        return { dot: 'bg-slate-400', bg: 'bg-slate-50', text: 'text-slate-600', border: 'border-slate-200', label: 'Queued', icon: <Clock className="w-4 h-4 text-slate-400" /> }
      case 'call_initiating':
        return { dot: 'bg-amber-500', bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', label: 'Initiating Call', icon: <Loader className="w-4 h-4 text-amber-500 animate-spin" /> }
      case 'call_connecting':
        return { dot: 'bg-orange-500', bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200', label: 'Connecting', icon: <Loader className="w-4 h-4 text-orange-500 animate-spin" /> }
      case 'call_in_progress':
        return { dot: 'bg-blue-500', bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200', label: 'In Call', icon: <Loader className="w-4 h-4 text-blue-500 animate-spin" /> }
      case 'call_ended':
        return { dot: 'bg-indigo-500', bg: 'bg-indigo-50', text: 'text-indigo-700', border: 'border-indigo-200', label: 'Call Ended', icon: <Phone className="w-4 h-4 text-indigo-500" /> }
      case 'transcribing':
        return { dot: 'bg-cyan-500', bg: 'bg-cyan-50', text: 'text-cyan-700', border: 'border-cyan-200', label: 'Transcribing', icon: <Loader className="w-4 h-4 text-cyan-500 animate-spin" /> }
      case 'evaluating':
        return { dot: 'bg-purple-500', bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200', label: 'Evaluating', icon: <Loader className="w-4 h-4 text-purple-500 animate-spin" /> }
      case 'fetching_details':
        return { dot: 'bg-indigo-500', bg: 'bg-indigo-50', text: 'text-indigo-700', border: 'border-indigo-200', label: 'Fetching Details', icon: <Loader className="w-4 h-4 text-indigo-500 animate-spin" /> }
      default:
        return { dot: 'bg-gray-400', bg: 'bg-gray-50', text: 'text-gray-600', border: 'border-gray-200', label: status, icon: null }
    }
  }

  const formatMetricValue = (value: any, type: string, metricName?: string): React.ReactNode => {
    if (value === null || value === undefined) return <span className="text-gray-300">--</span>
    
    const normalizedType = type?.toLowerCase()
    
    if (metricName === 'Emotion Category') {
      const emotion = String(value).toLowerCase()
      const emotionColors: Record<string, { bg: string; text: string }> = {
        'neutral': { bg: 'bg-slate-100', text: 'text-slate-700' },
        'happy': { bg: 'bg-emerald-100', text: 'text-emerald-700' },
        'sad': { bg: 'bg-blue-100', text: 'text-blue-700' },
        'angry': { bg: 'bg-rose-100', text: 'text-rose-700' },
        'fearful': { bg: 'bg-purple-100', text: 'text-purple-700' },
        'fear': { bg: 'bg-purple-100', text: 'text-purple-700' },
        'surprised': { bg: 'bg-amber-100', text: 'text-amber-700' },
        'surprise': { bg: 'bg-amber-100', text: 'text-amber-700' },
        'disgusted': { bg: 'bg-lime-100', text: 'text-lime-800' },
        'disgust': { bg: 'bg-lime-100', text: 'text-lime-800' },
        'calm': { bg: 'bg-teal-100', text: 'text-teal-700' },
      }
      const config = emotionColors[emotion] || { bg: 'bg-gray-100', text: 'text-gray-700' }
      return (
        <span className={`inline-flex items-center px-3 py-1.5 rounded-lg text-sm font-semibold capitalize ${config.bg} ${config.text}`}>
          {value}
        </span>
      )
    }
    
    if (normalizedType === 'boolean') {
      const boolValue = value === true || value === 1 || value === '1' || value === 'true'
      return boolValue ? (
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center">
            <CheckCircle className="w-4 h-4 text-emerald-600" />
          </div>
          <span className="text-lg font-bold text-emerald-700">Yes</span>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-rose-100 flex items-center justify-center">
            <XCircle className="w-4 h-4 text-rose-600" />
          </div>
          <span className="text-lg font-bold text-rose-700">No</span>
        </div>
      )
    }
    
    if (normalizedType === 'rating') {
      if (typeof value === 'string' && isNaN(parseFloat(value))) {
        return (
          <span className="inline-flex items-center px-3 py-1.5 rounded-lg bg-purple-50 text-purple-700 text-sm font-semibold capitalize">
            {value}
          </span>
        )
      }
      
      const numValue = typeof value === 'number' ? value : parseFloat(value)
      if (isNaN(numValue)) return <span className="text-gray-300">--</span>
      
      const normalizedValue = Math.max(0, Math.min(1, numValue))
      const percentage = Math.round(normalizedValue * 100)
      
      const getColor = (pct: number) => {
        if (pct >= 80) return { bar: 'bg-emerald-500', text: 'text-emerald-700', ring: 'text-emerald-500' }
        if (pct >= 60) return { bar: 'bg-amber-500', text: 'text-amber-700', ring: 'text-amber-500' }
        return { bar: 'bg-rose-500', text: 'text-rose-700', ring: 'text-rose-500' }
      }
      
      const color = getColor(percentage)
      
      return (
        <div className="flex flex-col gap-2">
          <div className="flex items-baseline gap-1">
            <span className={`text-2xl font-bold tabular-nums ${color.text}`}>{percentage}</span>
            <span className="text-sm text-gray-400">%</span>
          </div>
          <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
            <motion.div 
              className={`h-full rounded-full ${color.bar}`}
              initial={{ width: 0 }}
              animate={{ width: `${percentage}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            />
          </div>
        </div>
      )
    }
    
    if (normalizedType === 'number') {
      const numValue = typeof value === 'number' ? value : parseFloat(value)
      if (isNaN(numValue)) return <span className="text-gray-300">--</span>
      
      if (metricName && isAudioMetric(metricName)) {
        const audioInfo = getAudioMetricInfo(metricName)
        return (
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-bold text-gray-900 tabular-nums">{numValue.toFixed(2)}</span>
            {audioInfo?.unit && <span className="text-sm font-medium text-purple-500">{audioInfo.unit}</span>}
          </div>
        )
      }
      
      return <span className="text-2xl font-bold text-gray-900 tabular-nums">{numValue.toFixed(1)}</span>
    }
    
    return <span className="text-2xl font-bold text-gray-900">{String(value)}</span>
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <Loader className="w-8 h-8 text-indigo-500 animate-spin mx-auto" />
          <p className="text-sm text-gray-500 mt-3">Loading evaluation details...</p>
        </div>
      </div>
    )
  }

  if (error || !result) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12">
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-6 text-center">
          <XCircle className="w-10 h-10 text-rose-400 mx-auto mb-3" />
          <p className="text-sm font-medium text-rose-800">
            {error?.message || 'Result not found'}
          </p>
          <Button onClick={() => navigate('/results')} variant="ghost" size="sm" className="mt-4">
            <ArrowLeft className="w-4 h-4 mr-1.5" />
            Back to Results
          </Button>
        </div>
      </div>
    )
  }

  const resultData = result as EvaluatorResultDetail
  const statusConfig = getStatusConfig(resultData.status)

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-6">
        <Button
          variant="outline"
          onClick={() => navigate(isFromPlayground ? '/playground' : '/results')}
          leftIcon={<ArrowLeft className="h-4 w-4" />}
          className="mb-4"
        >
          Back to {isFromPlayground ? 'Playground' : 'Results'}
        </Button>
        
        <div className="bg-white shadow rounded-lg p-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">{resultData.name || 'Evaluation Result Details'}</h1>
              <p className="text-sm text-gray-500 mt-1">
                Result ID: <span className="font-mono font-semibold text-primary-600">{resultData.result_id}</span>
              </p>
            </div>
            <div className="flex items-center gap-3">
              {(resultData.status === 'completed' || resultData.status === 'failed') && resultData.evaluator_id && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => reEvaluateMutation.mutate(resultData.id)}
                  disabled={reEvaluateMutation.isPending}
                  isLoading={reEvaluateMutation.isPending}
                  leftIcon={!reEvaluateMutation.isPending ? <RotateCcw className="w-4 h-4" /> : undefined}
                >
                  Re-evaluate
                </Button>
              )}
              <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-semibold ${statusConfig.bg} ${statusConfig.text}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${statusConfig.dot}`} />
                {statusConfig.label}
              </span>
            </div>
          </div>

          {/* Metadata */}
          <div className="mt-6 grid grid-cols-2 md:grid-cols-5 gap-4">
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1">Status</p>
              <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${statusConfig.bg} ${statusConfig.text}`}>
                {statusConfig.label}
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

          {/* Extended details row */}
          {(resultData.scenario || resultData.persona || resultData.evaluator) && (
            <div className="mt-4 pt-4 border-t border-gray-100 grid grid-cols-2 md:grid-cols-5 gap-4">
              {resultData.scenario && (
                <div>
                  <p className="text-xs text-gray-500 font-medium mb-1">Scenario</p>
                  <p className="text-sm text-gray-900">{resultData.scenario.name}</p>
                  {resultData.scenario.description && (
                    <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{resultData.scenario.description}</p>
                  )}
                </div>
              )}
              {resultData.persona && (
                <div>
                  <p className="text-xs text-gray-500 font-medium mb-1">Persona Details</p>
                  <p className="text-xs text-gray-500">
                    {resultData.persona.language} &middot; {resultData.persona.accent} &middot; {resultData.persona.gender}
                  </p>
                </div>
              )}
              {resultData.evaluator && (
                <div>
                  <p className="text-xs text-gray-500 font-medium mb-1">Evaluator</p>
                  <p className="text-sm font-mono text-gray-900 text-xs">
                    {resultData.evaluator.evaluator_id}
                  </p>
                </div>
              )}
              {resultData.provider_platform && (
                <div>
                  <p className="text-xs text-gray-500 font-medium mb-1">Platform</p>
                  <p className="text-sm text-gray-900 capitalize">{resultData.provider_platform}</p>
                </div>
              )}
              {resultData.provider_call_id && (
                <div>
                  <p className="text-xs text-gray-500 font-medium mb-1">Provider Call ID</p>
                  <p className="text-sm font-mono text-gray-900 text-xs">
                    {resultData.provider_call_id}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Error Message */}
      {resultData.error_message && (
        <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800 font-semibold">Error:</p>
          <p className="text-red-700 mt-1">{resultData.error_message}</p>
        </div>
      )}

      {/* Evaluation Metrics */}
      <div className="mb-6 bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold text-gray-900 flex items-center mb-4">
          <BarChart3 className="w-5 h-5 mr-2" />
          Evaluation Metrics
          {resultData.result_id && (
            <span className="ml-2 text-sm font-mono text-gray-500">
              #{resultData.result_id}
            </span>
          )}
        </h2>
        
        <div>
          {/* Loading state */}
          {(resultData.status === 'evaluating' || resultData.status === 'transcribing' || resultData.status === 'queued') && (
            <div className="flex items-center justify-center py-12">
              <div className="text-center">
                <Loader className="w-6 h-6 text-indigo-500 animate-spin mx-auto mb-3" />
                <span className="text-sm text-gray-500">
                  {resultData.status === 'transcribing' ? 'Transcribing audio...' : 
                   resultData.status === 'queued' ? 'Evaluation queued...' : 'Evaluating conversation...'}
                </span>
              </div>
            </div>
          )}
          
          {/* Error state */}
          {resultData.status === 'failed' && !resultData.metric_scores && (
            <div className="text-center py-12">
              <XCircle className="w-8 h-8 text-gray-300 mx-auto mb-2" />
              <p className="text-sm text-gray-500">Evaluation failed. No metrics available.</p>
            </div>
          )}
          
          {/* Show metrics when completed */}
          {resultData.metric_scores && Object.keys(resultData.metric_scores).length > 0 &&
            (() => {
              const hasValidValue = (metric: { value: any }) => {
                const val = metric.value
                if (val === null || val === undefined) return false
                if (val === '') return false
                if (typeof val === 'string' && val.toLowerCase() === 'n/a') return false
                if (typeof val === 'string' && val.toLowerCase() === 'na') return false
                if (typeof val === 'string' && val.trim() === '') return false
                return true
              }
              
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
                <div className="space-y-8">
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
                            <div>{formatMetricValue(metric.value, metric.type, metric.metric_name)}</div>
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
                            <div>{formatMetricValue(metric.value, metric.type, metric.metric_name)}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {/* LLM Conversation Metrics */}
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
                            <div>{formatMetricValue(metric.value, metric.type, metric.metric_name)}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )
            })()}
          
          {/* No metrics available */}
          {resultData.status === 'completed' && (!resultData.metric_scores || Object.keys(resultData.metric_scores).length === 0) && (
            <div className="text-center py-8 text-gray-500">
              No evaluation metrics available.
            </div>
          )}
        </div>
      </div>

      {/* Call Data from Provider */}
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

      {resultData.call_data && resultData.provider_platform && resultData.provider_platform !== 'retell' && resultData.provider_platform !== 'vapi' && (
        <div className="mb-6 bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center mb-4">
            <Phone className="w-5 h-5 mr-2" />
            Call Details 
            <span className="ml-2 px-2 py-0.5 text-xs bg-gray-100 text-gray-800 rounded-full capitalize">
              {resultData.provider_platform}
            </span>
          </h2>
          <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-xs max-h-[600px]">
            {JSON.stringify(resultData.call_data, null, 2)}
          </pre>
        </div>
      )}

      {/* Transcript Section - for test agents without provider call_data */}
      {!resultData.call_data && (resultData.audio_s3_key || resultData.transcription || resultData.speaker_segments) && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          {/* Tab Navigation */}
          <div className="px-6 border-b border-gray-100 flex items-center gap-0">
            <button
              onClick={() => setActiveTab('overview')}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === 'overview'
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              Overview
            </button>
            <button
              onClick={() => setActiveTab('transcript')}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === 'transcript'
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              Transcript
            </button>
          </div>

          <div className="p-6">
            {/* Overview Tab */}
            {activeTab === 'overview' && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Transcript Preview (2 cols) */}
                <div className="lg:col-span-2">
                  <div className="rounded-xl border border-gray-100 bg-gray-50/30 flex flex-col h-[560px]">
                    <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
                      <div className="flex items-center gap-2">
                        <MessageSquare className="h-4 w-4 text-indigo-500" />
                        <span className="text-sm font-medium text-gray-900">Transcript</span>
                      </div>
                      {audioUrl && (
                        <div className="flex items-center gap-2">
                          <audio controls src={audioUrl} className="h-8 w-56" />
                          <a 
                            href={audioUrl} 
                            download 
                            className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                          >
                            <Download className="h-4 w-4" />
                          </a>
                        </div>
                      )}
                    </div>

                    <div className="flex-1 overflow-y-auto p-4 space-y-3">
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
                              <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 cursor-pointer transition-all ${
                                isUser
                                  ? 'bg-indigo-600 text-white rounded-br-sm'
                                  : 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm'
                              } ${isActive ? 'ring-2 ring-indigo-300 shadow-md' : ''}`}>
                                <div className={`flex items-center gap-2 mb-0.5 ${isUser ? 'text-indigo-200' : 'text-gray-400'}`}>
                                  <span className="text-[10px] font-semibold uppercase tracking-wider">
                                    {isUser ? 'Caller' : (resultData.agent?.name || 'Agent')}
                                  </span>
                                  <span className="text-[10px] tabular-nums">{formatTime(segment.start)}</span>
                                </div>
                                <p className="text-sm leading-relaxed">{segment.text}</p>
                              </div>
                            </div>
                          )
                        })
                      ) : resultData.transcription ? (
                        <div className="p-4 bg-white rounded-lg border border-gray-100">
                          <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{resultData.transcription}</p>
                        </div>
                      ) : (
                        <div className="text-center py-12 text-gray-500">
                          <MessageSquare className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                          <p className="text-sm">
                            {resultData.status === 'transcribing' ? 'Transcription in progress...' : 'No transcript available'}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Call Info Sidebar (1 col) */}
                <div className="lg:col-span-1 space-y-4">
                  <div className="rounded-xl border border-gray-100 bg-gray-50/30 p-5">
                    <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
                      <Phone className="h-4 w-4 text-indigo-500" />
                      Call Summary
                    </h3>
                    <div className="space-y-3">
                      <div className="p-3 bg-white rounded-lg border border-gray-100">
                        <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">Duration</p>
                        <p className="text-base font-semibold text-gray-900 tabular-nums">{formatDuration(getEffectiveDuration())}</p>
                      </div>
                      
                      <div className="p-3 bg-white rounded-lg border border-gray-100">
                        <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">Status</p>
                        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium border ${statusConfig.bg} ${statusConfig.text} ${statusConfig.border}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${statusConfig.dot}`} />
                          {statusConfig.label}
                        </span>
                      </div>

                      {resultData.agent && (
                        <div className="p-3 bg-white rounded-lg border border-gray-100">
                          <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">Agent</p>
                          <p className="text-sm font-medium text-gray-900">{resultData.agent.name}</p>
                          {resultData.agent.description && (
                            <p className="text-xs text-gray-500 mt-1 line-clamp-2">{resultData.agent.description}</p>
                          )}
                        </div>
                      )}

                      {resultData.persona && (
                        <div className="p-3 bg-white rounded-lg border border-gray-100">
                          <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">Persona</p>
                          <p className="text-sm font-medium text-gray-900">{resultData.persona.name}</p>
                          <div className="flex flex-wrap gap-1.5 mt-1.5">
                            <span className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">{resultData.persona.language}</span>
                            <span className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">{resultData.persona.accent}</span>
                            <span className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">{resultData.persona.gender}</span>
                          </div>
                        </div>
                      )}

                      {resultData.scenario && (
                        <div className="p-3 bg-white rounded-lg border border-gray-100">
                          <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold mb-1">Scenario</p>
                          <p className="text-sm font-medium text-gray-900">{resultData.scenario.name}</p>
                          {resultData.scenario.description && (
                            <p className="text-xs text-gray-500 mt-1 line-clamp-2">{resultData.scenario.description}</p>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Full Transcript Tab */}
            {activeTab === 'transcript' && (
              <div className="rounded-xl border border-gray-100 bg-gray-50/30 flex flex-col h-[650px]">
                <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <MessageSquare className="h-4 w-4 text-indigo-500" />
                    <span className="text-sm font-medium text-gray-900">Full Transcript</span>
                  </div>
                  {audioUrl && (
                    <div className="flex items-center gap-2">
                      <audio controls src={audioUrl} className="h-8 w-56" />
                      <a 
                        href={audioUrl} 
                        download 
                        className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                      >
                        <Download className="h-4 w-4" />
                      </a>
                    </div>
                  )}
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-3">
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
                          <div className={`max-w-[70%] rounded-2xl px-4 py-2.5 cursor-pointer transition-all ${
                            isUser
                              ? 'bg-indigo-600 text-white rounded-br-sm'
                              : 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm'
                          } ${isActive ? 'ring-2 ring-indigo-300 shadow-md' : ''}`}>
                            <div className={`flex items-center gap-2 mb-0.5 ${isUser ? 'text-indigo-200' : 'text-gray-400'}`}>
                              <span className="text-[10px] font-semibold uppercase tracking-wider">
                                {isUser ? 'Caller' : (resultData.agent?.name || 'Agent')}
                              </span>
                              <span className="text-[10px] tabular-nums">{formatTime(segment.start)}</span>
                            </div>
                            <p className="text-sm leading-relaxed">{segment.text}</p>
                          </div>
                        </div>
                      )
                    })
                  ) : resultData.transcription ? (
                    <div className="p-4 bg-white rounded-lg border border-gray-100">
                      <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{resultData.transcription}</p>
                    </div>
                  ) : (
                    <div className="text-center py-12 text-gray-500">
                      <MessageSquare className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                      <p className="text-sm">
                        {resultData.status === 'transcribing' ? 'Transcription in progress...' : 'No transcript available'}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Hidden audio element */}
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
        </div>
      )}
    </div>
  )
}
