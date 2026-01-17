import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { ArrowLeft, Clock, MessageSquare, TrendingUp, FileText, Play, Pause } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'

interface TestAgentResultData {
  id: string
  result_id: string
  name?: string | null
  timestamp: string
  duration_seconds: number | null
  status: 'queued' | 'transcribing' | 'evaluating' | 'completed' | 'failed'
  transcription?: string | null
  speaker_segments?: Array<{
    speaker: string
    text: string
    start: number
    end: number
  }> | null
  metric_scores?: Record<string, { value: any; type: string; metric_name: string }> | null
  audio_s3_key?: string | null
  agent?: {
    id: string
    name: string
    voice_bundle?: {
      name: string
      bundle_type: string
      s2s_model?: string | null
      llm_model?: string | null
    }
  }
}

export default function TestAgentResultDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { ToastContainer } = useToast()
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [audioDuration, setAudioDuration] = useState(0)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const { data: result, isLoading } = useQuery({
    queryKey: ['test-agent-result', id],
    queryFn: () => apiClient.getEvaluatorResult(id!, true),
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

  useEffect(() => {
    if (presignedUrl?.url && audioRef.current) {
      const audio = audioRef.current
      
      const updateTime = () => setCurrentTime(audio.currentTime)
      const updateDuration = () => setAudioDuration(audio.duration)
      const handleEnded = () => setIsPlaying(false)
      
      audio.addEventListener('timeupdate', updateTime)
      audio.addEventListener('loadedmetadata', updateDuration)
      audio.addEventListener('ended', handleEnded)
      
      return () => {
        audio.removeEventListener('timeupdate', updateTime)
        audio.removeEventListener('loadedmetadata', updateDuration)
        audio.removeEventListener('ended', handleEnded)
      }
    }
  }, [presignedUrl])

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

  const handlePlayPause = () => {
    if (!audioRef.current || !presignedUrl?.url) return

    if (isPlaying) {
      audioRef.current.pause()
      setIsPlaying(false)
    } else {
      audioRef.current.play()
      setIsPlaying(true)
    }
  }

  // Extract summary, sentiment, and successful from metric_scores
  const summaryMetric = result?.metric_scores?.summary || 
    (result?.metric_scores ? Object.values(result.metric_scores).find((m: any) => m.metric_name?.toLowerCase().includes('summary')) : null)
  const summary = (summaryMetric as any)?.value || 'Not Available'
  
  const sentimentMetric = result?.metric_scores?.sentiment || 
    (result?.metric_scores ? Object.values(result.metric_scores).find((m: any) => m.metric_name?.toLowerCase().includes('sentiment')) : null)
  const sentiment = (sentimentMetric as any)?.value || 'Not Available'
  
  const successfulMetric = result?.metric_scores?.successful || 
    (result?.metric_scores ? Object.values(result.metric_scores).find((m: any) => m.metric_name?.toLowerCase().includes('success')) : null)
  const successful = (successfulMetric as any)?.value !== undefined ? (successfulMetric as any).value : null

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-600">Loading result...</div>
      </div>
    )
  }

  if (!result) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <p className="text-gray-600 mb-4">Result not found</p>
          <Button variant="outline" onClick={() => navigate('/playground')}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Playground
          </Button>
        </div>
      </div>
    )
  }

  const resultData = result as TestAgentResultData

  return (
    <>
      <ToastContainer />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
          <Button
            variant="outline"
            onClick={() => navigate('/playground')}
            leftIcon={<ArrowLeft className="h-4 w-4" />}
            className="mb-4"
          >
            Back to Playground
          </Button>
          <div className="bg-white shadow rounded-lg p-6">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-2xl font-bold text-gray-900">Test Agent Call Details</h1>
                <p className="text-sm text-gray-500 mt-1">
                  Call ID: <span className="font-mono">{resultData.result_id}</span>
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Main Content - Matching RetellCallDetails structure */}
        <div className="space-y-6">
          {/* Call Overview */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-gray-50 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Clock className="h-4 w-4 text-gray-600" />
                <h4 className="font-semibold text-gray-900">Call Duration</h4>
              </div>
              <p className="text-2xl font-bold text-gray-900">{formatDuration(resultData.duration_seconds)}</p>
              <p className="text-sm text-gray-600 mt-1">
                Started: {formatTimestamp(resultData.timestamp)}
              </p>
            </div>

            <div className="bg-gray-50 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <h4 className="font-semibold text-gray-900">Platform</h4>
              </div>
              <p className="text-lg font-semibold text-gray-900">
                {resultData.agent?.voice_bundle?.name || 
                 (resultData.agent?.voice_bundle?.bundle_type === 's2s' 
                   ? resultData.agent?.voice_bundle?.s2s_model 
                   : resultData.agent?.voice_bundle?.llm_model) || 
                 'Test Agent'}
              </p>
            </div>
          </div>

          {/* Call Analysis */}
          <div className="bg-blue-50 rounded-lg p-4 border border-blue-200">
            <div className="flex items-center gap-2 mb-3">
              <TrendingUp className="h-4 w-4 text-blue-600" />
              <h4 className="font-semibold text-blue-900">Call Analysis</h4>
            </div>
            {summary && summary !== 'Not Available' && (
              <div className="mb-3">
                <p className="text-sm font-medium text-blue-900 mb-1">Summary:</p>
                <p className="text-sm text-blue-800">{summary}</p>
              </div>
            )}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div>
                <p className="text-xs text-blue-700 font-medium">Sentiment</p>
                <p className="text-sm text-blue-900 font-semibold">
                  {sentiment !== 'Not Available' ? sentiment : 'N/A'}
                </p>
              </div>
              <div>
                <p className="text-xs text-blue-700 font-medium">Successful</p>
                <p className="text-sm text-blue-900 font-semibold">
                  {successful !== null && successful !== undefined ? (successful ? 'Yes' : 'No') : 'N/A'}
                </p>
              </div>
            </div>
          </div>

          {/* Audio Player */}
          {resultData.audio_s3_key && presignedUrl?.url && (
            <div className="bg-gray-50 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <Play className="h-4 w-4 text-gray-600" />
                <h4 className="font-semibold text-gray-900">Audio Recording</h4>
              </div>
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
                    <span>{Math.floor(currentTime / 60)}:{(Math.floor(currentTime % 60)).toString().padStart(2, '0')}</span>
                    <span>{formatDuration(audioDuration || resultData.duration_seconds)}</span>
                  </div>
                  <div className="relative h-2 bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className="absolute top-0 left-0 h-full bg-blue-600 rounded-full transition-all"
                      style={{ 
                        width: `${audioDuration ? (currentTime / audioDuration) * 100 : 0}%` 
                      }}
                    />
                  </div>
                </div>
              </div>
              <audio
                ref={audioRef}
                src={presignedUrl.url}
                preload="metadata"
                className="hidden"
              />
            </div>
          )}

          {/* Transcript */}
          {resultData.transcription && (
            <div className="bg-gray-50 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <MessageSquare className="h-4 w-4 text-gray-600" />
                <h4 className="font-semibold text-gray-900">Transcript</h4>
              </div>
              <div className="bg-white rounded p-3 max-h-64 overflow-y-auto">
                <pre className="text-sm text-gray-800 whitespace-pre-wrap font-sans">
                  {resultData.transcription}
                </pre>
              </div>
            </div>
          )}

          {/* Detailed Transcript with Speaker Segments */}
          {resultData.speaker_segments && resultData.speaker_segments.length > 0 && (
            <div className="bg-gray-50 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <FileText className="h-4 w-4 text-gray-600" />
                <h4 className="font-semibold text-gray-900">Detailed Transcript</h4>
              </div>
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {resultData.speaker_segments.map((item, idx) => (
                  <div
                    key={idx}
                    className={`p-3 rounded ${
                      item.speaker === 'Speaker 1' || item.speaker?.toLowerCase().includes('user') 
                        ? 'bg-blue-50 border-l-4 border-blue-500' 
                        : 'bg-green-50 border-l-4 border-green-500'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-semibold text-gray-700 uppercase">
                        {item.speaker}
                      </span>
                      <span className="text-xs text-gray-500">
                        {item.start.toFixed(1)}s - {item.end.toFixed(1)}s
                      </span>
                    </div>
                    <p className="text-sm text-gray-900">{item.text}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Latency Metrics - Not Available */}
          <div className="bg-gray-50 rounded-lg p-4">
            <h4 className="font-semibold text-gray-900 mb-3">Latency Metrics</h4>
            <p className="text-sm text-gray-600">Not Available</p>
          </div>

          {/* Performance Metrics - Not Available */}
          <div className="bg-gray-50 rounded-lg p-4">
            <h4 className="font-semibold text-gray-900 mb-3">Performance Metrics</h4>
            <p className="text-sm text-gray-600">Not Available</p>
          </div>

          {/* Cost Breakdown - Not Available */}
          <div className="bg-gray-50 rounded-lg p-4">
            <h4 className="font-semibold text-gray-900 mb-3">Cost Breakdown</h4>
            <p className="text-sm text-gray-600">Not Available</p>
          </div>

          {/* Debug Data */}
          <div className="bg-gray-50 rounded-lg p-4">
            <h4 className="font-semibold text-gray-900 mb-3">Debug Data</h4>
            <p className="text-sm text-gray-600">No data available</p>
          </div>
        </div>
      </div>
    </>
  )
}

