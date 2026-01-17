import { Clock, MessageSquare, TrendingUp, FileText, Play, Pause } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'

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
}

interface TestVoiceAgentResultDetailsProps {
  resultData: TestVoiceAgentResultData
}

export default function TestVoiceAgentResultDetails({ resultData }: TestVoiceAgentResultDetailsProps) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [audioDuration, setAudioDuration] = useState(0)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    if (audioRef.current && resultData.audioUrl) {
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
  }, [resultData.audioUrl])

  const formatDuration = (seconds?: number | null) => {
    if (!seconds) return 'N/A'
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}m ${secs}s`
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const handlePlayPause = () => {
    if (!audioRef.current || !resultData.audioUrl) return

    if (isPlaying) {
      audioRef.current.pause()
      setIsPlaying(false)
    } else {
      audioRef.current.play()
      setIsPlaying(true)
    }
  }

  // Extract summary, sentiment, and successful from metric_scores or call_analysis
  const summary = resultData.call_analysis?.call_summary || 
    (resultData.metric_scores?.summary?.value) || 
    'Not Available'
  
  const sentiment = resultData.call_analysis?.user_sentiment || 
    (resultData.metric_scores?.sentiment?.value) || 
    'Not Available'
  
  const successful = resultData.call_analysis?.call_successful !== undefined 
    ? resultData.call_analysis.call_successful 
    : (resultData.metric_scores?.successful?.value !== undefined 
        ? resultData.metric_scores.successful.value 
        : null)

  return (
    <div className="space-y-6">
      {/* Audio Player */}
      {resultData.audioUrl && (
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="flex items-center gap-4">
            <button
              onClick={handlePlayPause}
              className="flex items-center justify-center w-12 h-12 rounded-full bg-blue-600 hover:bg-blue-700 text-white transition-colors"
              disabled={!resultData.audioUrl}
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
                <span>{formatTime(audioDuration || resultData.duration_seconds || 0)}</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-blue-600 h-2 rounded-full transition-all"
                  style={{
                    width: audioDuration ? `${(currentTime / audioDuration) * 100}%` : '0%',
                  }}
                />
              </div>
            </div>
          </div>
          <audio ref={audioRef} src={resultData.audioUrl} />
        </div>
      )}

      {/* Call Overview */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Clock className="h-4 w-4 text-gray-600" />
            <h4 className="font-semibold text-gray-900">Call Duration</h4>
          </div>
          <p className="text-2xl font-bold text-gray-900">
            {formatDuration(resultData.duration_seconds)}
          </p>
          {resultData.timestamp && (
            <p className="text-sm text-gray-600 mt-1">
              {new Date(resultData.timestamp).toLocaleString()}
            </p>
          )}
        </div>

        <div className="bg-gray-50 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="h-4 w-4 text-gray-600" />
            <h4 className="font-semibold text-gray-900">Status</h4>
          </div>
          <p className="text-2xl font-bold text-gray-900 capitalize">
            {resultData.status || 'Unknown'}
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
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <div>
            <p className="text-xs text-blue-700 font-medium">Sentiment</p>
            <p className="text-sm text-blue-900 font-semibold">
              {sentiment}
            </p>
          </div>
          <div>
            <p className="text-xs text-blue-700 font-medium">Successful</p>
            <p className="text-sm text-blue-900 font-semibold">
              {successful !== null ? (successful ? 'Yes' : 'No') : 'Not Available'}
            </p>
          </div>
        </div>
      </div>

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
            {resultData.speaker_segments.map((segment, idx) => (
              <div
                key={idx}
                className={`p-3 rounded ${
                  segment.speaker === 'agent' || segment.speaker === 'voice_agent'
                    ? 'bg-blue-50 border-l-4 border-blue-500'
                    : 'bg-green-50 border-l-4 border-green-500'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-semibold text-gray-700 uppercase">
                    {segment.speaker === 'agent' || segment.speaker === 'voice_agent' ? 'Agent' : 'User'}
                  </span>
                  <span className="text-xs text-gray-500">
                    {formatTime(segment.start)} - {formatTime(segment.end)}
                  </span>
                </div>
                <p className="text-sm text-gray-900">{segment.text}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Latency Metrics - Show as Not Available */}
      <div className="bg-gray-50 rounded-lg p-4">
        <h4 className="font-semibold text-gray-900 mb-3">Latency Metrics</h4>
        <p className="text-gray-600 text-sm">Not Available</p>
      </div>

      {/* Performance Metrics - Show as Not Available */}
      <div className="bg-gray-50 rounded-lg p-4">
        <h4 className="font-semibold text-gray-900 mb-3">Performance Metrics</h4>
        <p className="text-gray-600 text-sm">Not Available</p>
      </div>

      {/* Cost Breakdown - Show as Not Available */}
      <div className="bg-gray-50 rounded-lg p-4">
        <h4 className="font-semibold text-gray-900 mb-3">Cost Breakdown</h4>
        <p className="text-gray-600 text-sm">Not Available</p>
      </div>

      {/* Debug Data - Show as No data available */}
      <div className="bg-gray-50 rounded-lg p-4">
        <h4 className="font-semibold text-gray-900 mb-3">Debug Data</h4>
        <p className="text-gray-600 text-sm italic">No data available</p>
      </div>
    </div>
  )
}

