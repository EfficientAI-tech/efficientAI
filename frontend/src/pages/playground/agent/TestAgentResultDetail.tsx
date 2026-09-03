import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { getEvaluatorResultPlaceholder } from '../../../lib/evaluatorResultQuery'
import { Activity, ArrowLeft } from 'lucide-react'
import Button from '../../../components/Button'
import { useToast } from '../../../hooks/useToast'
import TestVoiceAgentResultDetails from '../../../components/call-recordings/TestVoiceAgentResultDetails'
import TraceDetailDrawer from '../../../components/call-recordings/TraceDetailDrawer'

export default function TestAgentResultDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { ToastContainer } = useToast()
  const queryClient = useQueryClient()
  const [traceDrawerOpen, setTraceDrawerOpen] = useState(false)

  const { data: result, isLoading } = useQuery({
    queryKey: ['evaluator-result', id],
    queryFn: () => apiClient.getEvaluatorResult(id!, true),
    enabled: !!id,
    placeholderData: () => (id ? getEvaluatorResultPlaceholder(queryClient, id) : undefined),
    staleTime: 30_000,
  })

  if (isLoading && !result) {
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

  const resultData = {
    ...result,
    call_analysis: result.call_data?.call_analysis || undefined,
  }

  const callShortId =
    typeof result.call_data?.call_short_id === 'string' ? result.call_data.call_short_id : null
  const platform = (result.provider_platform || '').toLowerCase()
  const useProviderDrawer =
    Boolean(callShortId) && ['vapi', 'retell', 'elevenlabs', 'smallest'].includes(platform)

  return (
    <>
      <ToastContainer />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
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
                <Button
                  variant="outline"
                  onClick={() => setTraceDrawerOpen(true)}
                  leftIcon={<Activity className="h-4 w-4" />}
                >
                  Call details
                </Button>
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

        <div className="bg-white shadow rounded-lg p-6">
          <TestVoiceAgentResultDetails resultData={resultData} metricsOnly />
        </div>
      </div>

      <TraceDetailDrawer
        open={traceDrawerOpen}
        callShortId={useProviderDrawer ? callShortId : null}
        evaluatorResultId={useProviderDrawer ? null : result.id}
        onClose={() => setTraceDrawerOpen(false)}
      />
    </>
  )
}
