import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import {
  Loader,
  ArrowLeft,
  Volume2,
  FileAudio,
  Clock,
  Mic,
} from 'lucide-react'
import Button from '../components/Button'
import { format } from 'date-fns'
import { useState, useEffect, useRef } from 'react'
import SpeakerWaveform from '../components/SpeakerWaveform'

export default function ManualTranscriptionDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioDuration, setAudioDuration] = useState<number>(0)
  const audioRef = useRef<HTMLAudioElement>(null)

  // Fetch transcription
  const { data: transcription, isLoading } = useQuery({
    queryKey: ['manual-evaluations', 'transcription', id],
    queryFn: () => apiClient.getManualTranscription(id!),
    enabled: !!id,
  })

  // Fetch presigned URL for audio
  const { data: presignedUrlData, isLoading: urlLoading } = useQuery({
    queryKey: ['manual-evaluations', 'presigned-url', transcription?.audio_file_key],
    queryFn: () => {
      if (!transcription?.audio_file_key) return null
      return apiClient.getAudioPresignedUrl(transcription.audio_file_key)
    },
    enabled: !!transcription?.audio_file_key,
  })

  useEffect(() => {
    if (presignedUrlData?.url) {
      setAudioUrl(presignedUrlData.url)
    }
  }, [presignedUrlData])

  useEffect(() => {
    const audio = audioRef.current
    if (audio) {
      const handleLoadedMetadata = () => {
        setAudioDuration(audio.duration)
      }
      audio.addEventListener('loadedmetadata', handleLoadedMetadata)
      return () => {
        audio.removeEventListener('loadedmetadata', handleLoadedMetadata)
      }
    }
  }, [audioUrl])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader className="h-8 w-8 animate-spin text-primary-600" />
      </div>
    )
  }

  if (!transcription) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Transcription not found</p>
        <Button
          variant="ghost"
          onClick={() => navigate('/evaluations?tab=manual')}
          className="mt-4"
        >
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to List
        </Button>
      </div>
    )
  }

  const getAudioFileName = (audioFileKey: string) => {
    return audioFileKey.split('/').pop() || audioFileKey
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <Button
            variant="ghost"
            onClick={() => navigate('/evaluations?tab=manual')}
            leftIcon={<ArrowLeft className="h-4 w-4" />}
          >
            Back
          </Button>
          <div>
            <h1 className="text-3xl font-bold text-gray-900">
              {transcription.name || `Transcription ${transcription.id.slice(0, 8)}`}
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              ID: {transcription.id}
            </p>
          </div>
        </div>
      </div>

      {/* Metadata Card */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Metadata</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="flex items-start">
            <FileAudio className="h-5 w-5 text-gray-400 mr-3 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-gray-500">Audio File</p>
              <p className="text-sm text-gray-900 truncate max-w-xs">
                {getAudioFileName(transcription.audio_file_key)}
              </p>
            </div>
          </div>
          <div className="flex items-start">
            <Mic className="h-5 w-5 text-gray-400 mr-3 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-gray-500">Model</p>
              <p className="text-sm text-gray-900">
                {transcription.stt_provider && (
                  <span className="capitalize">{transcription.stt_provider}</span>
                )}
                {transcription.stt_model && (
                  <span className="text-gray-500"> - {transcription.stt_model}</span>
                )}
              </p>
            </div>
          </div>
          <div className="flex items-start">
            <Clock className="h-5 w-5 text-gray-400 mr-3 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-gray-500">Processing Time</p>
              <p className="text-sm text-gray-900">
                {transcription.processing_time
                  ? `${transcription.processing_time.toFixed(2)}s`
                  : 'N/A'}
              </p>
            </div>
          </div>
          <div className="flex items-start">
            <Clock className="h-5 w-5 text-gray-400 mr-3 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-gray-500">Created</p>
              <p className="text-sm text-gray-900">
                {format(new Date(transcription.created_at), 'MMM d, yyyy HH:mm')}
              </p>
            </div>
          </div>
        </div>
        {transcription.language && (
          <div className="mt-4 pt-4 border-t border-gray-200">
            <p className="text-sm text-gray-500">
              <span className="font-medium">Language:</span> {transcription.language.toUpperCase()}
            </p>
          </div>
        )}
      </div>

      {/* Audio Player */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
          <Volume2 className="h-5 w-5 mr-2" />
          Audio Player
        </h2>
        {urlLoading ? (
          <div className="text-center py-8">
            <Loader className="h-6 w-6 animate-spin text-primary-600 mx-auto" />
          </div>
        ) : audioUrl ? (
          <div className="space-y-4">
            <audio
              ref={audioRef}
              src={audioUrl}
              className="w-full"
              controls
            />
            {transcription.speaker_segments && transcription.speaker_segments.length > 0 && (
              <SpeakerWaveform
                audioDuration={audioDuration}
                speakerSegments={transcription.speaker_segments}
                audioRef={audioRef}
              />
            )}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">
            Failed to load audio
          </div>
        )}
      </div>

      {/* Transcription */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Transcription</h2>
        {transcription.speaker_segments && transcription.speaker_segments.length > 0 ? (
          <div className="space-y-4">
            {transcription.speaker_segments.map((segment: { speaker: string; text: string; start: number; end: number }, idx: number) => {
              const startTime = formatTime(segment.start)
              const endTime = formatTime(segment.end)
              return (
                <div
                  key={idx}
                  className="border-l-4 pl-4 py-2"
                  style={{
                    borderColor: getSpeakerColor(segment.speaker),
                  }}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span
                      className="font-semibold text-sm"
                      style={{ color: getSpeakerColor(segment.speaker) }}
                    >
                      {segment.speaker}
                    </span>
                    <span className="text-xs text-gray-500">
                      {startTime} - {endTime}
                    </span>
                  </div>
                  <p className="text-gray-900">{segment.text}</p>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="prose max-w-none">
            <p className="text-gray-900 whitespace-pre-wrap">{transcription.transcript}</p>
          </div>
        )}
      </div>
    </div>
  )
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function getSpeakerColor(speaker: string): string {
  // Generate consistent colors for speakers
  const colors = [
    '#3B82F6', // Blue
    '#10B981', // Green
    '#F59E0B', // Amber
    '#EF4444', // Red
    '#8B5CF6', // Purple
    '#EC4899', // Pink
  ]
  const speakerNum = parseInt(speaker.replace(/\D/g, '')) || 0
  return colors[(speakerNum - 1) % colors.length] || '#6B7280'
}

