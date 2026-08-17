import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { ArrowLeft } from 'lucide-react'
import Button from '../../../components/Button'
import { useToast } from '../../../hooks/useToast'
import TestVoiceAgentResultDetails from '../../../components/call-recordings/TestVoiceAgentResultDetails'
import {
  useCallRecordingAudioUrls,
  useRecordingDownloadTracks,
} from '../../../hooks/useRecordingDownloadTracks'

function getResultAudioS3Key(result: any): string | null {
  const callData = result?.call_data
  return (
    callData?.stereo_recording_s3_key ||
    result?.audio_s3_key ||
    callData?.recording_s3_key ||
    callData?.mono_recording_s3_key ||
    null
  )
}

export default function TestAgentResultDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { ToastContainer } = useToast()

  const { data: result, isLoading } = useQuery({
    queryKey: ['test-agent-result', id],
    queryFn: () => apiClient.getEvaluatorResult(id!, true),
    enabled: !!id,
  })

  const audioS3Key = getResultAudioS3Key(result)
  const callShortId = result?.call_data?.call_short_id as string | undefined
  const { playbackUrl, waveformUrl } = useCallRecordingAudioUrls({
    callShortId,
    storageKey: audioS3Key,
    hasStorageRecording: !!audioS3Key,
  })
  const { tracks: downloadTracks, isLoading: downloadTracksLoading } = useRecordingDownloadTracks(
    result?.call_data,
  )

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

  // Prepare the result data with audio URL and extract call_analysis from call_data
  const resultData = {
    ...result,
    call_analysis: result.call_data?.call_analysis || undefined,
    audioUrl: playbackUrl || undefined,
    waveformUrl: waveformUrl || undefined,
    downloadTracks,
    downloadTracksLoading,
    recordingFormat: result.call_data?.recording_format || null,
  }

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
                  Call ID: <span className="font-mono font-semibold text-primary-600">{result.result_id}</span>
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className={`px-3 py-1 rounded-full text-sm font-semibold ${
                  result.status === 'completed'
                    ? 'bg-green-100 text-green-800'
                    : result.status === 'failed'
                    ? 'bg-red-100 text-red-800'
                    : 'bg-yellow-100 text-yellow-800'
                }`}>
                  {result.status}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Call Details - Using the same component structure as RetellCallDetails */}
        <div className="bg-white shadow rounded-lg p-6">
          <TestVoiceAgentResultDetails resultData={resultData} />
        </div>
      </div>
    </>
  )
}
