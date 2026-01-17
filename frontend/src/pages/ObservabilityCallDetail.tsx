import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'

import Button from '../components/Button'
import ConfirmModal from '../components/ConfirmModal'
import { apiClient } from '../lib/api'
import RetellCallDetails from '../components/call-recordings/RetellCallDetails'

export default function ObservabilityCallDetail() {
  const navigate = useNavigate()
  const { callShortId } = useParams<{ callShortId: string }>()
  const queryClient = useQueryClient()
  const [showDelete, setShowDelete] = useState(false)

  const {
    data: callRecording,
    isLoading,
  } = useQuery({
    queryKey: ['observability-call', callShortId],
    queryFn: () => apiClient.getObservabilityCall(callShortId!),
    enabled: !!callShortId,
  })

  const deleteMutation = useMutation({
    mutationFn: () => apiClient.deleteObservabilityCall(callShortId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['observability-calls'] })
      navigate('/observability/calls')
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-600">Loading call...</div>
      </div>
    )
  }

  if (!callRecording) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <p className="text-gray-600 mb-4">Call not found</p>
          <Button variant="outline" onClick={() => navigate('/observability/calls')}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Calls
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <Button
        variant="outline"
        onClick={() => navigate('/observability/calls')}
        leftIcon={<ArrowLeft className="h-4 w-4" />}
        className="mb-4"
      >
        Back to Calls
      </Button>

      <div className="bg-white shadow rounded-lg p-6 mb-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Call Details</h1>
            <p className="text-sm text-gray-500 mt-1">
              Call ID: <span className="font-mono">{callRecording.call_short_id}</span>
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="danger"
              onClick={() => setShowDelete(true)}
              isLoading={deleteMutation.isPending}
            >
              Delete
            </Button>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-xs text-gray-500 font-medium mb-1">Status</p>
            <span
              className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                callRecording.status === 'UPDATED'
                  ? 'bg-green-100 text-green-800'
                  : 'bg-yellow-100 text-yellow-800'
              }`}
            >
              {callRecording.status}
            </span>
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium mb-1">Event</p>
            <EventBadge event={callRecording.call_event} />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium mb-1">Platform</p>
            <PlatformBadge platform={callRecording.provider_platform} />
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
              {callRecording.created_at ? new Date(callRecording.created_at).toLocaleString() : 'N/A'}
            </p>
          </div>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg p-6">
        {callRecording.provider_platform === 'retell' && callRecording.call_data ? (
          <RetellCallDetails callData={callRecording.call_data} />
        ) : (
          <>
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Call Data (JSON)</h2>
            <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-xs">
              {JSON.stringify(callRecording.call_data, null, 2)}
            </pre>
          </>
        )}
      </div>

      <ConfirmModal
        title="Delete call"
        description="This will permanently remove this call record."
        isOpen={showDelete}
        isLoading={deleteMutation.isPending}
        onCancel={() => setShowDelete(false)}
        onConfirm={() => deleteMutation.mutate()}
      />
    </div>
  )
}

function EventBadge({ event }: { event?: string }) {
  if (!event) {
    return <span className="text-gray-400">—</span>
  }

  const normalized = event.toLowerCase()
  const variants: Record<
    string,
    { icon: string; label: string; color: string; accent?: string; pulse?: boolean }
  > = {
    call_started: {
      icon: '',
      label: 'Call started',
      color: 'bg-blue-100 text-blue-800',
      accent: 'bg-blue-400',
      pulse: true,
    },
    call_ended: {
      icon: '✅',
      label: 'Call ended',
      color: 'bg-emerald-100 text-emerald-800',
      accent: 'bg-emerald-400',
    },
    call_analyzed: {
      icon: '🧠',
      label: 'Call analyzed',
      color: 'bg-purple-100 text-purple-800',
    },
  }

  const variant =
    variants[normalized] || {
      icon: 'ℹ️',
      label: event,
      color: 'bg-gray-100 text-gray-700',
    }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${variant.color}`}
    >
      {variant.pulse && variant.accent ? (
        <span className="relative flex h-3 w-3">
          <span
            className={`absolute inline-flex h-full w-full rounded-full ${variant.accent} opacity-60 animate-ping`}
          />
          <span className={`relative inline-flex h-3 w-3 rounded-full ${variant.accent}`} />
        </span>
      ) : null}
      <span className="leading-none">{variant.icon}</span>
      <span className="leading-none">{variant.label}</span>
    </span>
  )
}

function PlatformBadge({ platform }: { platform?: string }) {
  if (!platform) return <span className="text-gray-400">N/A</span>
  const normalized = platform.toLowerCase()

  const logos: Record<string, string> = {
    retell: '/retellai.png',
    vapi: '/vapi.png',
  }

  const label = normalized.charAt(0).toUpperCase() + normalized.slice(1)
  const logo = logos[normalized]

  return (
    <span className="inline-flex items-center gap-2 text-sm text-gray-700">
      {logo && <img src={logo} alt={label} className="h-5 w-5 object-contain" />}
      <span className="capitalize">{label}</span>
    </span>
  )
}

