import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Eye, RefreshCw, PhoneCall, Info, Sparkles } from 'lucide-react'

import Button from '../components/Button'
import { apiClient } from '../lib/api'
import ConfirmModal from '../components/ConfirmModal'

export default function ObservabilityCalls() {
  const navigate = useNavigate()

  const {
    data: calls = [],
    isLoading,
    refetch,
  } = useQuery({
  const [selectedCallId, setSelectedCallId] = React.useState<string | null>(null)
  const deleteMutation = useMutation({
    mutationFn: (callShortId: string) => apiClient.deleteObservabilityCall(callShortId),
    onSuccess: () => {
      setSelectedCallId(null)
      refetch()
    },
  })
    queryKey: ['observability-calls'],
    queryFn: () => apiClient.listObservabilityCalls(),
  })

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Live tracking indicator */}
      <div className="mb-4 flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 shadow-sm">
        <div className="relative h-3 w-3">
          <span className="absolute inset-0 rounded-full bg-amber-400 animate-ping"></span>
          <span className="absolute inset-0 rounded-full bg-amber-500"></span>
        </div>
        <div className="flex items-center gap-2 text-sm text-amber-800 font-medium">
          <Sparkles className="h-4 w-4" />
          <span>Live: receiving and updating call webhooks</span>
        </div>
      </div>

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Calls</h1>
          <p className="text-sm text-gray-600 mt-1">
            Ingested call events from your voice AI providers via webhook.
          </p>
        </div>
        <Button variant="outline" size="sm" leftIcon={<RefreshCw className="h-4 w-4" />} onClick={() => refetch()}>
          Refresh
        </Button>
      </div>

      <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 mb-6 flex gap-3 items-start">
        <Info className="h-5 w-5 text-blue-500 mt-0.5" />
        <div className="text-sm text-blue-800">
          Configure your provider webhook to POST to <code className="font-mono">/api/v1/observability/calls</code>{' '}
          with the <code className="font-mono">X-EFFICIENTAI-API-KEY</code> header. Payloads are stored per
          organization and surfaced here.
        </div>
      </div>

      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <PhoneCall className="h-5 w-5 text-gray-500" />
            <h2 className="text-lg font-semibold text-gray-900">Call Events</h2>
          </div>
          <span className="text-sm text-gray-500">Total: {calls.length}</span>
        </div>

        {isLoading ? (
          <div className="p-6 text-gray-600">Loading calls...</div>
        ) : calls.length === 0 ? (
          <div className="p-6 text-gray-600">No calls have been ingested yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Call ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Event
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Platform
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Provider Call ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Created
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {calls.map((call: any) => (
                  <tr key={call.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <button
                        onClick={() => navigate(`/observability/calls/${call.call_short_id}`)}
                        className="font-mono text-sm font-medium text-blue-600 hover:text-blue-800 hover:underline"
                      >
                        {call.call_short_id}
                      </button>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600 capitalize">
                      <EventBadge event={call.call_event} />
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span
                        className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                          call.status === 'UPDATED'
                            ? 'bg-green-100 text-green-800'
                            : 'bg-yellow-100 text-yellow-800'
                        }`}
                      >
                        {call.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <PlatformBadge platform={call.provider_platform} />
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500 font-mono text-xs">
                      {call.provider_call_id || 'N/A'}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
                      {call.created_at ? new Date(call.created_at).toLocaleString() : 'N/A'}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm font-medium">
                      <button
                        onClick={() => navigate(`/observability/calls/${call.call_short_id}`)}
                        className="text-blue-600 hover:text-blue-900"
                        aria-label="View call"
                      >
                        <Eye className="h-4 w-4" />
                      </button>
                      <button
                        onClick={() => setSelectedCallId(call.call_short_id)}
                        className="ml-3 text-red-600 hover:text-red-800"
                        aria-label="Delete call"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ConfirmModal
        title="Delete call"
        description="This will permanently remove this call record."
        isOpen={!!selectedCallId}
        isLoading={deleteMutation.isPending}
        onCancel={() => setSelectedCallId(null)}
        onConfirm={() => selectedCallId && deleteMutation.mutate(selectedCallId)}
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

