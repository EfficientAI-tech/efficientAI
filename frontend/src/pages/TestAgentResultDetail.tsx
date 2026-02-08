import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { ArrowLeft } from 'lucide-react'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'
import TestVoiceAgentResultDetails from '../components/call-recordings/TestVoiceAgentResultDetails'

export default function TestAgentResultDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { ToastContainer } = useToast()

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

  // Prepare the result data with audio URL
  const resultData = {
    ...result,
    audioUrl: presignedUrl?.url || undefined,
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
                  Call ID: <span className="font-mono">{result.result_id}</span>
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
