import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Eye, RefreshCw, PhoneCall, Info, Activity, CheckCircle,
  Clock, Loader, Trash2, PhoneOff, PhoneIncoming, Copy, Check, ChevronDown, ChevronUp,
} from 'lucide-react'
import { motion } from 'framer-motion'

import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import { apiClient } from '../../lib/api'
import { getIntegrationPlatformLabel, getIntegrationPlatformLogo } from '../../config/providers'
import {
  IntegrationPlatform,
  ObservabilityCall,
  ObservabilityCallsSummary,
  ObservabilityLiveLatencyResponse,
} from '../../types/api'
import { CallAgentLink } from './CallAgentLink'

export default function ObservabilityCalls() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null)
  const [eventFilter, setEventFilter] = useState<'all' | 'call_ended' | 'call_started' | 'other'>('all')
  const [copiedWebhook, setCopiedWebhook] = useState<string | null>(null)
  const [showSetupGuide, setShowSetupGuide] = useState(false)

  const webhookBaseUrl = useMemo(() => {
    const envBase = (import.meta as { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL
    if (envBase && envBase.trim()) return envBase.replace(/\/$/, '')
    if (typeof window !== 'undefined') return window.location.origin
    return ''
  }, [])

  const webhookEndpoints = useMemo(
    () => [
      '/api/v1/observability/calls/webhook/{api_key}',
      '/api/v1/observability/calls/webhook/retell/{api_key}',
      '/api/v1/observability/calls/webhook/elevenlabs/{api_key}',
      '/api/v1/observability/calls/webhook/vapi/{api_key}',
    ],
    [],
  )

  const copyWebhookUrl = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopiedWebhook(value)
      setTimeout(() => setCopiedWebhook((current) => (current === value ? null : current)), 2000)
    } catch {
      // no-op: clipboard may be blocked by browser permissions
    }
  }

  const deleteMutation = useMutation({
    mutationFn: (callShortId: string) => apiClient.deleteObservabilityCall(callShortId),
    onSuccess: () => {
      setSelectedCallId(null)
      queryClient.invalidateQueries({ queryKey: ['observability-calls'] })
      queryClient.invalidateQueries({ queryKey: ['observability-calls-summary'] })
    },
  })

  const {
    data: calls = [],
    isLoading,
  } = useQuery<ObservabilityCall[]>({
    queryKey: ['observability-calls'],
    queryFn: () => apiClient.listObservabilityCalls(),
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data || !Array.isArray(data)) return false
      const hasLive = data.some((call) => call.is_live)
      return hasLive ? 3000 : false
    },
  })

  const { data: summary } = useQuery<ObservabilityCallsSummary>({
    queryKey: ['observability-calls-summary'],
    queryFn: () => apiClient.getObservabilityCallsSummary(),
  })
  const liveDashboardEnabled = Boolean(summary?.live_feature_flags?.live_dashboard_enabled)
  const liveAggregatesEnabled = Boolean(summary?.live_feature_flags?.live_aggregates_enabled)
  const { data: liveLatency } = useQuery<ObservabilityLiveLatencyResponse>({
    queryKey: ['observability-live-latency'],
    queryFn: () => apiClient.getObservabilityLiveLatencyMetrics(),
    enabled: liveDashboardEnabled && liveAggregatesEnabled,
    refetchInterval: 5000,
  })

  const summaryStats = useMemo(() => {
    const total = summary?.total_calls ?? calls.length
    const ended = summary?.event_breakdown?.call_ended ?? calls.filter((c) => c.call_event === 'call_ended').length
    const started = summary?.event_breakdown?.call_started ?? calls.filter((c) => c.call_event === 'call_started').length
    const other = total - ended - started
    return {
      total,
      ended,
      started,
      other,
      totalMinutes: summary?.total_minutes ?? 0,
      avgDurationMs: summary?.avg_duration_ms ?? summary?.avg_latency_ms ?? 0,
      traceLinkedCalls: summary?.trace_linked_calls ?? calls.filter((c) => !!c.trace_id).length,
      traceLinkRatePct: summary?.trace_link_rate_pct ?? (total > 0 ? (calls.filter((c) => !!c.trace_id).length / total) * 100 : 0),
      traceAvailableCalls: summary?.trace_available_calls ?? calls.filter((c) => !!c.trace_id).length,
      traceAvailableRatePct:
        summary?.trace_available_rate_pct ??
        (total > 0 ? (calls.filter((c) => !!c.trace_id).length / total) * 100 : 0),
      evaluatedCalls: summary?.evaluated_calls ?? calls.filter((c) => !!c.evaluator_result_id).length,
      evaluatedRatePct: summary?.evaluated_rate_pct ?? (total > 0 ? (calls.filter((c) => !!c.evaluator_result_id).length / total) * 100 : 0),
    }
  }, [calls, summary])

  const filteredCalls = useMemo(() => {
    if (eventFilter === 'all') return calls
    if (eventFilter === 'call_ended') return calls.filter((c) => c.call_event === 'call_ended')
    if (eventFilter === 'call_started') return calls.filter((c) => c.call_event === 'call_started')
    return calls.filter((c) => c.call_event !== 'call_ended' && c.call_event !== 'call_started')
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
        <div className="text-sm text-blue-800 w-full">
          <p>Use webhook URLs with your API key:</p>
          <div className="mt-2 space-y-2">
            {webhookEndpoints.map((path) => {
              const fullUrl = `${webhookBaseUrl}${path}`
              const copied = copiedWebhook === fullUrl
              return (
                <div key={path} className="flex items-center gap-2">
                  <code className="block font-mono bg-blue-100 px-1.5 py-0.5 rounded text-xs flex-1 break-all">
                    {fullUrl}
                  </code>
                  <button
                    type="button"
                    onClick={() => copyWebhookUrl(fullUrl)}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded border border-blue-200 bg-white text-blue-700 hover:bg-blue-50"
                    aria-label={`Copy webhook url ${path}`}
                  >
                    {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                </div>
              )
            })}
          </div>
          Include <code className="font-mono bg-blue-100 px-1.5 py-0.5 rounded text-xs">trace_id</code> in payloads to link traces.
          <button
            type="button"
            onClick={() => setShowSetupGuide((current) => !current)}
            className="mt-3 inline-flex items-center gap-1 text-blue-700 hover:text-blue-900 font-medium"
          >
            Setup guide
            {showSetupGuide ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          {showSetupGuide && (
            <div className="mt-2 rounded border border-blue-200 bg-white p-3 text-xs text-blue-900 space-y-1">
              <p>Required fields: <code className="font-mono">id</code>, <code className="font-mono">trace_id</code>, and <code className="font-mono">messages</code>.</p>
              <p>Use ISO-8601 UTC for <code className="font-mono">startedAt</code> and <code className="font-mono">endedAt</code>.</p>
              <p>Provider-specific payload mapping is documented in <code className="font-mono">docs/telemetry/provider-webhook-map.md</code>.</p>
            </div>
          )}
        </div>
      </div>

      {/* Summary Stats */}
      {!isLoading && calls.length > 0 && (
        <motion.div
          className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4"
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
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Total Minutes</p>
                <p className="text-2xl font-bold text-emerald-600 mt-1">
                  {summaryStats.totalMinutes.toFixed(1)}
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center">
                <CheckCircle className="w-5 h-5 text-emerald-500" />
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-1">minutes</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Avg Duration</p>
                <p className="text-2xl font-bold text-blue-600 mt-1">
                  {Math.round(summaryStats.avgDurationMs)}
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center">
                <PhoneIncoming className="w-5 h-5 text-blue-500" />
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-1">ms</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Ended</p>
                <p className="text-2xl font-bold text-amber-600 mt-1">{summaryStats.ended}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-amber-50 flex items-center justify-center">
                <Clock className="w-5 h-5 text-amber-500" />
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Trace Available</p>
                <p className="text-2xl font-bold text-violet-600 mt-1">{summaryStats.traceAvailableCalls}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-violet-50 flex items-center justify-center">
                <Activity className="w-5 h-5 text-violet-500" />
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-1">{summaryStats.traceAvailableRatePct.toFixed(1)}% available</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Evaluated</p>
                <p className="text-2xl font-bold text-purple-600 mt-1">{summaryStats.evaluatedCalls}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-purple-50 flex items-center justify-center">
                <CheckCircle className="w-5 h-5 text-purple-500" />
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-1">{summaryStats.evaluatedRatePct.toFixed(1)}% of calls</p>
          </div>
        </motion.div>
      )}

      {liveDashboardEnabled && liveAggregatesEnabled && liveLatency && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Live Quality (Rolling)</h3>
            <span className="text-xs text-gray-500">1m / 5m windows</span>
          </div>
          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
            <LivePercentileCard
              label="P50"
              oneMinute={liveLatency.windows['60s'].p50_ms}
              fiveMinute={liveLatency.windows['300s'].p50_ms}
            />
            <LivePercentileCard
              label="P90"
              oneMinute={liveLatency.windows['60s'].p90_ms}
              fiveMinute={liveLatency.windows['300s'].p90_ms}
            />
            <LivePercentileCard
              label="P95"
              oneMinute={liveLatency.windows['60s'].p95_ms}
              fiveMinute={liveLatency.windows['300s'].p95_ms}
            />
          </div>
          <div className="mt-4 text-xs text-gray-500">
            Samples: {liveLatency.windows['60s'].sample_count} (1m) / {liveLatency.windows['300s'].sample_count} (5m)
          </div>
        </div>
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
                    Agent
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Provider Call ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Last Live Event
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
                {filteredCalls.map((call) => (
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
                      <EventBadge event={call.call_event ?? undefined} />
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <PlatformBadge platform={call.provider_platform ?? undefined} />
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      <CallAgentLink agent={call.agent} />
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <span
                        className="text-xs font-mono text-gray-500 truncate block max-w-[160px]"
                        title={call.provider_call_id ?? undefined}
                      >
                        {call.provider_call_id || 'N/A'}
                      </span>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-500">
                        {call.last_live_event_ts ? formatTimestamp(call.last_live_event_ts) : 'N/A'}
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

function LivePercentileCard({
  label,
  oneMinute,
  fiveMinute,
}: {
  label: string
  oneMinute?: number | null
  fiveMinute?: number | null
}) {
  const format = (value?: number | null) => (typeof value === 'number' ? `${Math.round(value)} ms` : 'N/A')
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
      <p className="text-xs font-medium text-gray-600">{label}</p>
      <p className="text-sm font-semibold text-gray-900 mt-1">{format(oneMinute)}</p>
      <p className="text-xs text-gray-500 mt-0.5">1m</p>
      <p className="text-sm font-semibold text-gray-900 mt-2">{format(fiveMinute)}</p>
      <p className="text-xs text-gray-500 mt-0.5">5m</p>
    </div>
  )
}

function EventBadge({ event }: { event?: string }) {
  if (!event) return <span className="text-gray-400">&mdash;</span>

  const variants: Record<string, { label: string; bg: string; text: string; border: string; dot: string; pulse?: boolean }> = {
    outbound_initiated: {
      label: 'Ringing',
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      border: 'border-amber-200',
      dot: 'bg-amber-500',
      pulse: true,
    },
    ringing: {
      label: 'Ringing',
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      border: 'border-amber-200',
      dot: 'bg-amber-500',
      pulse: true,
    },
    call_in_progress: {
      label: 'In Progress',
      bg: 'bg-sky-50',
      text: 'text-sky-700',
      border: 'border-sky-200',
      dot: 'bg-sky-500',
      pulse: true,
    },
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
    failed: {
      label: 'Failed',
      bg: 'bg-rose-50',
      text: 'text-rose-700',
      border: 'border-rose-200',
      dot: 'bg-rose-500',
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
      <span className={`w-1.5 h-1.5 rounded-full ${variant.dot} ${variant.pulse ? 'animate-pulse' : ''}`} />
      {variant.label}
    </span>
  )
}

function PlatformBadge({ platform }: { platform?: string }) {
  if (!platform) return <span className="text-gray-400">N/A</span>
  const normalized = platform.toLowerCase() as IntegrationPlatform
  const label = getIntegrationPlatformLabel(normalized)
  const logo = getIntegrationPlatformLogo(normalized)

  return (
    <span className="inline-flex items-center gap-2 text-sm text-gray-700">
      {logo && <img src={logo} alt={label} className="h-5 w-5 object-contain" />}
      <span>{label}</span>
    </span>
  )
}
