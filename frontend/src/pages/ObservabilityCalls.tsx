import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Eye, RefreshCw, PhoneCall, Info, Activity, CheckCircle,
  Clock, Loader, Trash2, PhoneOff, PhoneIncoming,
} from 'lucide-react'
import { motion } from 'framer-motion'

import Button from '../components/Button'
import ConfirmModal from '../components/ConfirmModal'
import { apiClient } from '../lib/api'

export default function ObservabilityCalls() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null)
  const [eventFilter, setEventFilter] = useState<'all' | 'call_ended' | 'call_started' | 'other'>('all')

  const deleteMutation = useMutation({
    mutationFn: (callShortId: string) => apiClient.deleteObservabilityCall(callShortId),
    onSuccess: () => {
      setSelectedCallId(null)
      queryClient.invalidateQueries({ queryKey: ['observability-calls'] })
    },
  })

  const {
    data: calls = [],
    isLoading,
  } = useQuery({
    queryKey: ['observability-calls'],
    queryFn: () => apiClient.listObservabilityCalls(),
  })

  const summaryStats = useMemo(() => {
    const total = calls.length
    const ended = calls.filter((c: any) => c.call_event === 'call_ended').length
    const started = calls.filter((c: any) => c.call_event === 'call_started').length
    const other = total - ended - started
    return { total, ended, started, other }
  }, [calls])

  const filteredCalls = useMemo(() => {
    if (eventFilter === 'all') return calls
    if (eventFilter === 'call_ended') return calls.filter((c: any) => c.call_event === 'call_ended')
    if (eventFilter === 'call_started') return calls.filter((c: any) => c.call_event === 'call_started')
    return calls.filter((c: any) => c.call_event !== 'call_ended' && c.call_event !== 'call_started')
  }, [calls, eventFilter])

  const formatTimestamp = (timestamp: string): string => {
    const date = new Date(timestamp)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Calls</h1>
          <p className="mt-2 text-sm text-gray-600">
            Ingested call records from your voice AI providers
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => queryClient.invalidateQueries({ queryKey: ['observability-calls'] })}
          disabled={isLoading}
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Webhook info */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 flex gap-3 items-start">
        <Info className="h-5 w-5 text-blue-500 mt-0.5 flex-shrink-0" />
        <div className="text-sm text-blue-800">
          POST call data to{' '}
          <code className="font-mono bg-blue-100 px-1.5 py-0.5 rounded text-xs">/api/v1/observability/calls</code>{' '}
          with the{' '}
          <code className="font-mono bg-blue-100 px-1.5 py-0.5 rounded text-xs">X-EFFICIENTAI-API-KEY</code>{' '}
          header. Payloads are stored per organization and surfaced here.
        </div>
      </div>

      {/* Summary Stats */}
      {!isLoading && calls.length > 0 && (
        <motion.div
          className="grid grid-cols-2 md:grid-cols-4 gap-4"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Total</p>
                <p className="text-2xl font-bold text-gray-900 mt-1">{summaryStats.total}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center">
                <Activity className="w-5 h-5 text-slate-600" />
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Ended</p>
                <p className="text-2xl font-bold text-emerald-600 mt-1">{summaryStats.ended}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center">
                <CheckCircle className="w-5 h-5 text-emerald-500" />
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Started</p>
                <p className="text-2xl font-bold text-blue-600 mt-1">{summaryStats.started}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center">
                <PhoneIncoming className="w-5 h-5 text-blue-500" />
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Other</p>
                <p className="text-2xl font-bold text-amber-600 mt-1">{summaryStats.other}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-amber-50 flex items-center justify-center">
                <Clock className="w-5 h-5 text-amber-500" />
              </div>
            </div>
          </div>
        </motion.div>
      )}

      {/* Call Records Table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <PhoneCall className="h-5 w-5 text-gray-500" />
              <h2 className="text-lg font-semibold text-gray-900">Call Records</h2>
            </div>
            {calls.length > 0 && (
              <div className="flex items-center gap-1">
                {([
                  { key: 'all' as const, label: 'All', count: summaryStats.total },
                  { key: 'call_ended' as const, label: 'Ended', count: summaryStats.ended },
                  { key: 'call_started' as const, label: 'Started', count: summaryStats.started },
                  { key: 'other' as const, label: 'Other', count: summaryStats.other },
                ] as const).map(({ key, label, count }) => (
                  <button
                    key={key}
                    onClick={() => setEventFilter(key)}
                    className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                      eventFilter === key
                        ? 'bg-primary-100 text-primary-800 border border-primary-300'
                        : 'text-gray-600 hover:bg-gray-100 border border-transparent'
                    }`}
                  >
                    {label} ({count})
                  </button>
                ))}
              </div>
            )}
          </div>
          <span className="text-sm text-gray-500">{filteredCalls.length} calls</span>
        </div>

        {isLoading ? (
          <div className="p-12 text-center">
            <Loader className="w-6 h-6 text-indigo-500 animate-spin mx-auto mb-3" />
            <p className="text-sm text-gray-500">Loading calls...</p>
          </div>
        ) : calls.length === 0 ? (
          <div className="p-12 text-center">
            <PhoneOff className="w-8 h-8 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-500 mb-1">No calls have been ingested yet.</p>
            <p className="text-xs text-gray-400">Send call data to the webhook endpoint to see them here.</p>
          </div>
        ) : filteredCalls.length === 0 ? (
          <div className="p-12 text-center">
            <p className="text-gray-500 mb-2">No matching calls found.</p>
            <button
              onClick={() => setEventFilter('all')}
              className="text-sm text-primary-600 hover:text-primary-800 font-medium"
            >
              Show all calls
            </button>
          </div>
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
                    Platform
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Provider Call ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Created
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {filteredCalls.map((call: any) => (
                  <tr
                    key={call.id}
                    className="hover:bg-gray-50 transition-colors cursor-pointer"
                    onClick={() => navigate(`/observability/calls/${call.call_short_id}`)}
                  >
                    <td className="px-4 py-4 whitespace-nowrap">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          navigate(`/observability/calls/${call.call_short_id}`)
                        }}
                        className="font-mono font-semibold text-primary-600 hover:text-primary-800 hover:underline"
                      >
                        {call.call_short_id}
                      </button>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <EventBadge event={call.call_event} />
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <PlatformBadge platform={call.provider_platform} />
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <span
                        className="text-xs font-mono text-gray-500 truncate block max-w-[160px]"
                        title={call.provider_call_id}
                      >
                        {call.provider_call_id || 'N/A'}
                      </span>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-500">
                        {call.created_at ? formatTimestamp(call.created_at) : 'N/A'}
                      </span>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => navigate(`/observability/calls/${call.call_short_id}`)}
                          leftIcon={<Eye className="w-4 h-4" />}
                        >
                          View
                        </Button>
                        <button
                          onClick={() => setSelectedCallId(call.call_short_id)}
                          className="p-1.5 text-gray-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
                          aria-label="Delete call"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
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
  if (!event) return <span className="text-gray-400">&mdash;</span>

  const variants: Record<string, { label: string; bg: string; text: string; border: string; dot: string }> = {
    call_started: {
      label: 'Call Started',
      bg: 'bg-blue-50',
      text: 'text-blue-700',
      border: 'border-blue-200',
      dot: 'bg-blue-500',
    },
    call_ended: {
      label: 'Call Ended',
      bg: 'bg-emerald-50',
      text: 'text-emerald-700',
      border: 'border-emerald-200',
      dot: 'bg-emerald-500',
    },
    call_analyzed: {
      label: 'Call Analyzed',
      bg: 'bg-purple-50',
      text: 'text-purple-700',
      border: 'border-purple-200',
      dot: 'bg-purple-500',
    },
  }

  const variant = variants[event.toLowerCase()] || {
    label: event,
    bg: 'bg-gray-50',
    text: 'text-gray-600',
    border: 'border-gray-200',
    dot: 'bg-gray-400',
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${variant.bg} ${variant.text} ${variant.border}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${variant.dot}`} />
      {variant.label}
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
