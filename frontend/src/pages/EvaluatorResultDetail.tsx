import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { apiClient } from '../lib/api'
import { ArrowLeft, Play, Pause, Clock, CheckCircle, XCircle, Loader, User, Bot, FileText, BarChart3, Phone } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'
import Button from '../components/Button'
import RetellCallDetails from '../components/call-recordings/RetellCallDetails'

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
  const [isPlaying, setIsPlaying] = useState(false)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [audioDuration, setAudioDuration] = useState(0)
  const [activeSegmentIndex, setActiveSegmentIndex] = useState<number | null>(null)
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

  const handlePlayPause = () => {
    if (!audioRef.current || !audioUrl) return

    if (isPlaying) {
      audioRef.current.pause()
      setIsPlaying(false)
    } else {
      audioRef.current.play()
      setIsPlaying(true)
    }
  }

  // Update current time and active segment
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !audioUrl) return

    const updateTime = () => {
      if (audio.readyState >= 2) { // HAVE_CURRENT_DATA or higher
        setCurrentTime(audio.currentTime)
        
        // Update duration if available
        if (audio.duration && audio.duration !== Infinity) {
          setAudioDuration(audio.duration)
        }
        
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
    }

    const handleLoadedMetadata = () => {
      if (audio.duration && audio.duration !== Infinity) {
        setAudioDuration(audio.duration)
      }
    }

    const handleTimeUpdate = () => {
      updateTime()
    }

    audio.addEventListener('loadedmetadata', handleLoadedMetadata)
    audio.addEventListener('timeupdate', handleTimeUpdate)
    audio.addEventListener('loadeddata', handleLoadedMetadata)
    audio.addEventListener('canplay', handleLoadedMetadata)
    
    // Initial update
    updateTime()

    return () => {
      audio.removeEventListener('loadedmetadata', handleLoadedMetadata)
      audio.removeEventListener('timeupdate', handleTimeUpdate)
      audio.removeEventListener('loadeddata', handleLoadedMetadata)
      audio.removeEventListener('canplay', handleLoadedMetadata)
    }
  }, [result, audioUrl])

  // Map speaker labels to friendly names
  const getSpeakerName = (speaker: string): string => {
    // Speaker 1 is typically the User/Test Agent, Speaker 2 is the Voice AI Agent
    if (speaker === 'Speaker 1') return 'User / Test Agent'
    if (speaker === 'Speaker 2') return 'Voice AI Agent'
    return speaker
  }

  const getSpeakerColor = (speaker: string): string => {
    if (speaker === 'Speaker 1') return 'bg-blue-50 border-blue-200 text-blue-900'
    if (speaker === 'Speaker 2') return 'bg-green-50 border-green-200 text-green-900'
    return 'bg-gray-50 border-gray-200 text-gray-900'
  }

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const handleSegmentClick = (startTime: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = startTime
      if (!isPlaying) {
        audioRef.current.play()
        setIsPlaying(true)
      }
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

  const formatTimestamp = (timestamp: string): string => {
    return new Date(timestamp).toLocaleString()
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

  const formatMetricValue = (value: any, type: string, _metricName?: string): React.ReactNode => {
    if (value === null || value === undefined) return <span className="text-gray-400">N/A</span>
    
    // Normalize type to lowercase for consistent comparison
    const normalizedType = type?.toLowerCase()
    
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
    
    // Handle number metrics
    if (normalizedType === 'number') {
      const numValue = typeof value === 'number' ? value : parseFloat(value)
      if (isNaN(numValue)) return <span className="text-gray-400">N/A</span>
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
    <div className="p-6 w-full">
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
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">
              Evaluation Result: {resultData.result_id}
            </h1>
            <p className="text-gray-600 mt-1">{resultData.name}</p>
          </div>
          <div className="flex items-center space-x-3">
            {getStatusIcon(resultData.status)}
            <span className={getStatusBadge(resultData.status)}>
              {resultData.status.toUpperCase().replace('_', ' ')}
            </span>
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
      {resultData.metric_scores && Object.keys(resultData.metric_scores).length > 0 && (
        <div className="mb-6 bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-xl font-semibold text-gray-900 flex items-center mb-4">
            <BarChart3 className="w-5 h-5 mr-2" />
            Evaluation Metrics
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {Object.entries(resultData.metric_scores).map(([metricId, metric]) => (
              <div key={metricId} className="border border-gray-200 rounded-lg p-4">
                <div className="text-sm font-medium text-gray-500 mb-2">
                  {metric.metric_name || metricId}
                </div>
                <div>
                  {formatMetricValue(metric.value, metric.type, metric.metric_name)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Call Data from Provider (Retell/Vapi) - Show this prominently when available */}
      {/* Show RetellCallDetails if provider_platform is 'retell' OR if call_data has retell-like structure */}
      {resultData.call_data && (resultData.provider_platform === 'retell' || resultData.call_data.transcript_object || resultData.call_data.call_id?.startsWith('call_')) && (
        <div className="mb-6 bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center mb-4">
            <Phone className="w-5 h-5 mr-2" />
            Call Details 
            <span className="ml-2 px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded-full capitalize">
              {resultData.provider_platform || 'retell'}
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

      {/* Non-Retell call_data - show raw JSON */}
      {resultData.call_data && resultData.provider_platform && resultData.provider_platform !== 'retell' && !resultData.call_data.transcript_object && (
        <div className="mb-6 bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center mb-4">
            <Phone className="w-5 h-5 mr-2" />
            Call Details 
            <span className="ml-2 px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded-full capitalize">
              {resultData.provider_platform}
            </span>
          </h2>
          <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-xs max-h-96">
            {JSON.stringify(resultData.call_data, null, 2)}
          </pre>
        </div>
      )}

      {/* Main Content Grid - Only show old audio/transcription when NO call_data */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column - 2 columns */}
        <div className="lg:col-span-2 space-y-6">
          {/* Playback Section - Audio Player (only when no call_data, since RetellCallDetails has its own player) */}
          {!resultData.call_data && (resultData.audio_s3_key || resultData.call_data?.recording_url) && (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-semibold text-gray-900 flex items-center">
                  <Play className="w-5 h-5 mr-2" />
                  Audio Recording
                </h2>
                <div className="flex items-center text-sm text-gray-500">
                  <Clock className="w-4 h-4 mr-1" />
                  {formatDuration(getEffectiveDuration())}
                </div>
              </div>
              {audioUrl ? (
                <div className="space-y-4">
                  <div className="flex items-center space-x-4">
                    <button
                      onClick={handlePlayPause}
                      className="flex items-center justify-center w-12 h-12 rounded-full bg-blue-600 hover:bg-blue-700 text-white transition-colors"
                    >
                      {isPlaying ? (
                        <Pause className="w-6 h-6" />
                      ) : (
                        <Play className="w-6 h-6 ml-1" />
                      )}
                    </button>
                    <div className="flex-1">
                      <div className="flex items-center justify-between text-sm text-gray-600 mb-2">
                        <span>{formatTime(currentTime)}</span>
                        <span>{formatTime(audioDuration || resultData?.duration_seconds || 0)}</span>
                      </div>
                      <div 
                        className="relative h-4 bg-gray-200 rounded-full overflow-hidden cursor-pointer border border-gray-300"
                        onClick={(e) => {
                          if (!audioRef.current) return
                          const duration = audioDuration || resultData?.duration_seconds || 1
                          if (duration <= 0) return
                          const rect = e.currentTarget.getBoundingClientRect()
                          const clickX = e.clientX - rect.left
                          const percentage = Math.max(0, Math.min(1, clickX / rect.width))
                          const newTime = percentage * duration
                          audioRef.current.currentTime = newTime
                        }}
                      >
                        {/* Speaker segments timeline (background layer) */}
                        {resultData?.speaker_segments && (audioDuration || resultData?.duration_seconds) && resultData.speaker_segments.map((segment, index) => {
                          const duration = audioDuration || resultData.duration_seconds || 1
                          const left = ((segment.start / duration) * 100)
                          const width = (((segment.end - segment.start) / duration) * 100)
                          const isActive = activeSegmentIndex === index
                          const color = segment.speaker === 'Speaker 1' ? 'bg-blue-300' : 'bg-green-300'
                          
                          return (
                            <div
                              key={index}
                              className={`absolute top-0 h-full ${color} ${isActive ? 'opacity-60' : 'opacity-30'} hover:opacity-50 transition-opacity`}
                              style={{ left: `${left}%`, width: `${width}%`, zIndex: 1 }}
                              title={`${getSpeakerName(segment.speaker)}: ${formatTime(segment.start)} - ${formatTime(segment.end)}`}
                            />
                          )
                        })}
                        {/* Progress bar (foreground layer) */}
                        {(audioDuration || resultData?.duration_seconds) && (
                          <div
                            className="absolute top-0 left-0 h-full bg-blue-600 rounded-full transition-all duration-100 z-10 shadow-sm"
                            style={{ 
                              width: `${Math.min(100, Math.max(0, ((currentTime / (audioDuration || resultData?.duration_seconds || 1)) * 100)))}%` 
                            }}
                          />
                        )}
                        {/* Clickable overlay for segment navigation */}
                        {resultData?.speaker_segments && (audioDuration || resultData?.duration_seconds) && resultData.speaker_segments.map((segment, index) => {
                          const duration = audioDuration || resultData.duration_seconds || 1
                          const left = ((segment.start / duration) * 100)
                          const width = (((segment.end - segment.start) / duration) * 100)
                          
                          return (
                            <div
                              key={`clickable-${index}`}
                              className="absolute top-0 h-full cursor-pointer"
                              style={{ left: `${left}%`, width: `${width}%`, zIndex: 20 }}
                              onClick={(e) => {
                                e.stopPropagation()
                                handleSegmentClick(segment.start)
                              }}
                              title={`${getSpeakerName(segment.speaker)}: ${formatTime(segment.start)} - ${formatTime(segment.end)}`}
                            />
                          )
                        })}
                      </div>
                    </div>
                  </div>
                  <audio
                    ref={audioRef}
                    src={audioUrl}
                    preload="metadata"
                    onEnded={() => {
                      setIsPlaying(false)
                      setCurrentTime(0)
                      setActiveSegmentIndex(null)
                    }}
                    onPause={() => setIsPlaying(false)}
                    onPlay={() => setIsPlaying(true)}
                    onLoadedMetadata={() => {
                      if (audioRef.current?.duration && audioRef.current.duration !== Infinity) {
                        setAudioDuration(audioRef.current.duration)
                      }
                    }}
                    className="hidden"
                  />
                  {/* Speaker legend */}
                  {resultData?.speaker_segments && resultData.speaker_segments.length > 0 && (
                    <div className="flex items-center space-x-4 text-xs">
                      <div className="flex items-center space-x-2">
                        <div className="w-3 h-3 bg-blue-400 rounded" />
                        <span>User / Test Agent</span>
                      </div>
                      <div className="flex items-center space-x-2">
                        <div className="w-3 h-3 bg-green-400 rounded" />
                        <span>Voice AI Agent</span>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-gray-500 text-sm">
                  {(resultData.audio_s3_key && !presignedUrl) ? 'Loading audio...' : 'Audio not available'}
                </div>
              )}
            </div>
          )}

          {/* Agent and Evaluation Details - Below Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Evaluation Details */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Evaluation Details</h2>
              <div className="space-y-3 text-sm">
                <div>
                  <div className="text-gray-500">Result ID</div>
                  <div className="font-mono font-semibold text-gray-900">{resultData.result_id}</div>
                </div>
                <div>
                  <div className="text-gray-500">Timestamp</div>
                  <div className="text-gray-900">{formatTimestamp(resultData.timestamp)}</div>
                </div>
                <div>
                  <div className="text-gray-500">Duration</div>
                  <div className="text-gray-900 flex items-center">
                    <Clock className="w-4 h-4 mr-1" />
                    {formatDuration(getEffectiveDuration())}
                  </div>
                </div>
              </div>
            </div>

            {/* Agent */}
            {resultData.agent && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <h2 className="text-lg font-semibold text-gray-900 flex items-center mb-4">
                  <Bot className="w-5 h-5 mr-2" />
                  Agent
                </h2>
                <div className="space-y-2 text-sm">
                  <div>
                    <div className="text-gray-500">Name</div>
                    <div className="font-medium text-gray-900">{resultData.agent.name}</div>
                  </div>
                  <div>
                    <div className="text-gray-500">Phone</div>
                    <div className="text-gray-900">
                      {resultData.agent.call_medium === 'web_call' ? (
                        <span className="italic text-gray-500">Not applicable - Web Call</span>
                      ) : resultData.agent.phone_number ? (
                        resultData.agent.phone_number
                      ) : (
                        <span className="text-gray-400">-</span>
                      )}
                    </div>
                  </div>
                  {resultData.agent.description && (
                    <div>
                      <div className="text-gray-500">Description</div>
                      <div className="text-gray-900">{resultData.agent.description}</div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Persona and Scenario - Additional Details */}
          {(resultData.persona || resultData.scenario) && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Persona */}
              {resultData.persona && (
                <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                  <h2 className="text-lg font-semibold text-gray-900 flex items-center mb-4">
                    <User className="w-5 h-5 mr-2" />
                    Persona
                  </h2>
                  <div className="space-y-2 text-sm">
                    <div>
                      <div className="text-gray-500">Name</div>
                      <div className="font-medium text-gray-900">{resultData.persona.name}</div>
                    </div>
                    <div>
                      <div className="text-gray-500">Language</div>
                      <div className="text-gray-900 capitalize">{resultData.persona.language}</div>
                    </div>
                    <div>
                      <div className="text-gray-500">Accent</div>
                      <div className="text-gray-900 capitalize">{resultData.persona.accent}</div>
                    </div>
                    <div>
                      <div className="text-gray-500">Gender</div>
                      <div className="text-gray-900 capitalize">{resultData.persona.gender}</div>
                    </div>
                    <div>
                      <div className="text-gray-500">Background Noise</div>
                      <div className="text-gray-900 capitalize">{resultData.persona.background_noise}</div>
                    </div>
                  </div>
                </div>
              )}

              {/* Scenario */}
              {resultData.scenario && (
                <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                  <h2 className="text-lg font-semibold text-gray-900 mb-4">Scenario</h2>
                  <div className="space-y-2 text-sm">
                    <div>
                      <div className="text-gray-500">Name</div>
                      <div className="font-medium text-gray-900">{resultData.scenario.name}</div>
                    </div>
                    {resultData.scenario.description && (
                      <div>
                        <div className="text-gray-500">Description</div>
                        <div className="text-gray-900">{resultData.scenario.description}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Evaluator */}
          {resultData.evaluator && (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Evaluator</h2>
              <div className="space-y-2 text-sm">
                <div>
                  <div className="text-gray-500">ID</div>
                  <div className="font-mono font-semibold text-gray-900">{resultData.evaluator.evaluator_id}</div>
                </div>
                <div>
                  <div className="text-gray-500">Name</div>
                  <div className="font-medium text-gray-900">{resultData.evaluator.name}</div>
                </div>
              </div>
            </div>
          )}

        </div>

        {/* Right Column - Transcription (only show when no call_data, since RetellCallDetails has transcript) */}
        {!resultData.call_data && (
          <div className="lg:col-span-1">
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 sticky top-6">
              <h2 className="text-xl font-semibold text-gray-900 flex items-center mb-4">
                <FileText className="w-5 h-5 mr-2" />
                Transcription
              </h2>
              <div className="max-h-[calc(100vh-200px)] overflow-y-auto">
                {resultData.speaker_segments && resultData.speaker_segments.length > 0 ? (
                  <div className="space-y-3">
                    {resultData.speaker_segments.map((segment, index) => {
                      const isActive = activeSegmentIndex === index
                      const speakerName = getSpeakerName(segment.speaker)
                      const speakerColor = getSpeakerColor(segment.speaker)
                      
                      return (
                        <div
                          key={index}
                          onClick={() => handleSegmentClick(segment.start)}
                          className={`
                            border-2 rounded-lg p-4 cursor-pointer transition-all
                            ${isActive ? 'ring-2 ring-blue-500 shadow-md' : 'hover:shadow-sm'}
                            ${speakerColor}
                          `}
                        >
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center space-x-2">
                              <span className="font-semibold text-sm">{speakerName}</span>
                              <span className="text-xs opacity-75">
                                {formatTime(segment.start)} - {formatTime(segment.end)}
                              </span>
                            </div>
                            {isActive && isPlaying && (
                              <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
                            )}
                          </div>
                          <p className="text-gray-900 whitespace-pre-wrap text-sm">{segment.text}</p>
                        </div>
                      )
                    })}
                  </div>
                ) : resultData.transcription ? (
                  <div className="prose max-w-none">
                    <p className="text-gray-700 whitespace-pre-wrap text-sm">{resultData.transcription}</p>
                  </div>
                ) : (
                  <div className="text-gray-500 italic text-sm">
                    {resultData.status === 'transcribing' ? 'Transcription in progress...' : 'No transcription available'}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

