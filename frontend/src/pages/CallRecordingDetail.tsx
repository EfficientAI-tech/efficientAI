import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { ArrowLeft, RefreshCw, Trash2 } from 'lucide-react'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'
import RetellCallDetails from '../components/call-recordings/RetellCallDetails'
import VapiCallDetails from '../components/call-recordings/VapiCallDetails'

export default function CallRecordingDetail() {
  const { callShortId } = useParams<{ callShortId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()

  const { data: callRecording, refetch: refetchCallDetails, isLoading } = useQuery({
    queryKey: ['call-recording', callShortId],
    queryFn: () => apiClient.getCallRecording(callShortId!),
    enabled: !!callShortId,
  })

  const refreshMutation = useMutation({
    mutationFn: () => apiClient.refreshCallRecording(callShortId!),
    onSuccess: () => {
      showToast('Call recording refresh initiated', 'success')
      setTimeout(() => {
        refetchCallDetails()
      }, 2000)
    },
    onError: (error: any) => {
      showToast(`Failed to refresh: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => apiClient.deleteCallRecording(callShortId!),
    onSuccess: () => {
      showToast('Call recording deleted successfully', 'success')
      queryClient.invalidateQueries({ queryKey: ['call-recordings'] })
      navigate('/playground')
    },
    onError: (error: any) => {
      showToast(`Failed to delete: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const handleDelete = () => {
    if (window.confirm('Are you sure you want to delete this call recording? This action cannot be undone.')) {
      deleteMutation.mutate()
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-600">Loading call recording...</div>
      </div>
    )
  }

  if (!callRecording) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <p className="text-gray-600 mb-4">Call recording not found</p>
          <Button variant="outline" onClick={() => navigate('/playground')}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Playground
          </Button>
        </div>
      </div>
    )
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
                <h1 className="text-2xl font-bold text-gray-900">Call Recording Details</h1>
                <p className="text-sm text-gray-500 mt-1">
                  Call ID: <span className="font-mono">{callRecording.call_short_id}</span>
                </p>
              </div>
              <div className="flex gap-2">
                {callRecording.status === 'PENDING' && (
                  <Button
                    variant="outline"
                    onClick={() => refreshMutation.mutate()}
                    leftIcon={<RefreshCw className="h-4 w-4" />}
                    isLoading={refreshMutation.isPending}
                  >
                    Refresh
                  </Button>
                )}
                <Button
                  variant="danger"
                  onClick={handleDelete}
                  leftIcon={<Trash2 className="h-4 w-4" />}
                  isLoading={deleteMutation.isPending}
                >
                  Delete
                </Button>
              </div>
            </div>

            {/* Metadata */}
            <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Status</p>
                <span
                  className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${callRecording.status === 'UPDATED'
                    ? 'bg-green-100 text-green-800'
                    : 'bg-yellow-100 text-yellow-800'
                    }`}
                >
                  {callRecording.status}
                </span>
              </div>
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Platform</p>
                <div className="flex items-center gap-2">
                  {callRecording.provider_platform?.toLowerCase() === 'retell' && (
                    <img
                      src="/retellai.png"
                      alt="Retell"
                      className="h-5 w-5 object-contain"
                    />
                  )}
                  <p className="text-sm text-gray-900 capitalize">{callRecording.provider_platform || 'N/A'}</p>
                </div>
              </div>
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Provider Call ID</p>
                <p className="text-sm font-mono text-gray-900 text-xs">
                  {callRecording.provider_call_id || 'N/A'}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Created</p>
                <p className="text-sm text-gray-900">
                  {callRecording.created_at
                    ? new Date(callRecording.created_at).toLocaleString()
                    : 'N/A'}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Call Data */}
        <div className="bg-white shadow rounded-lg p-6">
          {callRecording.provider_platform === 'retell' && callRecording.call_data ? (
            <RetellCallDetails callData={callRecording.call_data} />
          ) : callRecording.call_data ? (
            <VapiCallDetails callData={callRecording.call_data} />
          ) : (
            <>
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Call Data (JSON)</h2>
              <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-xs">
                {JSON.stringify(callRecording.call_data, null, 2)}
              </pre>
            </>
          )}
        </div>
      </div>
    </>
  )
}

