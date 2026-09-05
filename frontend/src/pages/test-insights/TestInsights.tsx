import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  Activity,
  BookOpen,
  Check,
  Copy,
  Eye,
  Loader,
  PhoneCall,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import TraceDetailDrawer from '../../components/call-recordings/TraceDetailDrawer'
import { FAILURE_FLAG_LABELS } from '../../components/call-recordings/traceUtils'
import { CallAgentLink } from '../observability/CallAgentLink'
import { EventBadge, PlatformBadge } from '../observability/observabilityCallUi'
import { ObservabilityCall } from '../../types/api'
import { useWorkspaceStore } from '../../store/workspaceStore'

type Tab = 'runs' | 'setup'
type StatusFilter = 'all' | 'open' | 'closed'
type EventFilter = 'all' | 'call_ended' | 'call_started' | 'other'

const PAGE_SIZE = 25

const tracesQueryKey = (
  workspaceId: string | null,
  page: number,
  status: StatusFilter,
) => ['observability-traces', workspaceId, page, status] as const

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString()
}

function formatRelative(iso: string): string {
  const date = new Date(iso)
  const diffMs = Date.now() - date.getTime()
  const mins = Math.floor(diffMs / 60000)
  const hours = Math.floor(diffMs / 3600000)
  const days = Math.floor(diffMs / 86400000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days < 7) return `${days}d ago`
  return date.toLocaleDateString()
}

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard.writeText(text).then(
          () => {
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
          },
          () => {},
        )
      }}
      className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-800"
      title={label ?? 'Copy'}
    >
      {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function StatusLabel({ status }: { status: string }) {
  const open = status === 'open'
  const label = status === 'finalized' ? 'closed' : status
  return (
    <span className={`text-sm capitalize ${open ? 'text-amber-700 font-medium' : 'text-gray-600'}`}>
      {open && <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 mr-1.5 align-middle" />}
      {label}
    </span>
  )
}

export default function TestInsights() {
  const queryClient = useQueryClient()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const [searchParams, setSearchParams] = useSearchParams()
  const resultFromUrl = searchParams.get('result')
  const traceFromUrl = searchParams.get('trace')
  const obsFromUrl = searchParams.get('obs')
  const [tab, setTab] = useState<Tab>('runs')
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(traceFromUrl)
  const [selectedObsCallId, setSelectedObsCallId] = useState<string | null>(obsFromUrl)
  const [selectedEvaluatorResultId, setSelectedEvaluatorResultId] = useState<string | null>(resultFromUrl)
  const [deleteObsCallId, setDeleteObsCallId] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [eventFilter, setEventFilter] = useState<EventFilter>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const prevWorkspaceRef = useRef<string | null>(null)

  const apiStatus = statusFilter === 'all' ? undefined : statusFilter

  const {
    data: listData,
    isLoading: loadingList,
    isFetching: fetchingList,
    isError: listError,
    error: listErrorDetail,
    refetch: refetchTraces,
    dataUpdatedAt,
  } = useQuery({
    queryKey: tracesQueryKey(activeWorkspaceId, page, statusFilter),
    queryFn: () =>
      apiClient.listSyntheticCallTraces({
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        status: apiStatus,
      }),
    enabled: tab === 'runs' && Boolean(activeWorkspaceId),
    retry: false,
    staleTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  const { data: setup, isLoading: loadingSetup } = useQuery({
    queryKey: ['synthetic-call-trace-setup'],
    queryFn: () => apiClient.getSyntheticCallTraceSetup(),
    enabled: tab === 'setup',
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  const {
    data: observabilityCalls = [],
    isLoading: loadingObsCalls,
    isFetching: fetchingObsCalls,
    refetch: refetchObsCalls,
  } = useQuery<ObservabilityCall[]>({
    queryKey: ['observability-calls', activeWorkspaceId],
    queryFn: () => apiClient.listObservabilityCalls(),
    enabled: tab === 'runs' && Boolean(activeWorkspaceId),
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data || !Array.isArray(data)) return false
      const production = data.filter((call) => call.source !== 'playground')
      return production.some((call) => call.is_live) ? 3000 : false
    },
  })

  const deleteObsMutation = useMutation({
    mutationFn: (callShortId: string) => apiClient.deleteObservabilityCall(callShortId),
    onSuccess: (_data, callShortId) => {
      setDeleteObsCallId(null)
      setSelectedObsCallId((current) => (current === callShortId ? null : current))
      const next = new URLSearchParams(searchParams)
      if (next.get('obs') === callShortId) {
        next.delete('obs')
        setSearchParams(next, { replace: true })
      }
      void queryClient.invalidateQueries({ queryKey: ['observability-calls'] })
    },
  })

  const traces = listData?.items ?? []
  const totalCount = listData?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))

  const productionObsCalls = useMemo(
    () => observabilityCalls.filter((call) => call.source !== 'playground'),
    [observabilityCalls],
  )

  const filteredTraces = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return traces
    return traces.filter((t: { call_short_id?: string; id?: string; transport?: string }) => {
      const id = (t.call_short_id ?? t.id ?? '').toLowerCase()
      const transport = (t.transport ?? '').toLowerCase()
      return id.includes(q) || transport.includes(q)
    })
  }, [traces, searchQuery])

  const filteredObsCalls = useMemo(() => {
    let rows = productionObsCalls
    if (eventFilter === 'call_ended') {
      rows = rows.filter((c) => c.call_event === 'call_ended')
    } else if (eventFilter === 'call_started') {
      rows = rows.filter((c) => c.call_event === 'call_started')
    } else if (eventFilter === 'other') {
      rows = rows.filter(
        (c) => c.call_event !== 'call_ended' && c.call_event !== 'call_started',
      )
    }
    const q = searchQuery.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((call) => {
      const id = (call.call_short_id ?? '').toLowerCase()
      const providerId = (call.provider_call_id ?? '').toLowerCase()
      const agentName = (call.agent?.name ?? '').toLowerCase()
      return id.includes(q) || providerId.includes(q) || agentName.includes(q)
    })
  }, [productionObsCalls, eventFilter, searchQuery])

  const eventSummary = useMemo(() => {
    const total = productionObsCalls.length
    const ended = productionObsCalls.filter((c) => c.call_event === 'call_ended').length
    const started = productionObsCalls.filter((c) => c.call_event === 'call_started').length
    const other = total - ended - started
    return { total, ended, started, other }
  }, [productionObsCalls])

  const showPipelineRows = true
  const showProviderRows = true
  const hasListRows =
    (showPipelineRows && filteredTraces.length > 0) ||
    (showProviderRows && filteredObsCalls.length > 0)

  const summaryStats = useMemo(() => {
    const open = traces.filter((t: { status?: string }) => t.status === 'open').length
    const closed = traces.filter(
      (t: { status?: string }) => t.status === 'closed' || t.status === 'finalized',
    ).length
    const withLatency = traces.filter(
      (t: { response_latency_p50_ms?: number | null }) => t.response_latency_p50_ms != null,
    ).length
    return { open, closed, withLatency }
  }, [traces])

  const providerSummary = useMemo(() => {
    const ended = productionObsCalls.filter((c) => c.call_event === 'call_ended').length
    const live = productionObsCalls.filter((c) => c.is_live).length
    return { total: productionObsCalls.length, ended, live }
  }, [productionObsCalls])

  const listErrorMessage =
    listError && listErrorDetail instanceof Error
      ? listErrorDetail.message
      : listError
        ? 'Could not load traces'
        : null

  const envBlock = setup?.one_time_env_vars
    ? Object.entries(setup.one_time_env_vars)
        .map(([k, v]) => `${k}=${v}`)
        .join('\n')
    : ''

  const openTrace = (traceId: string) => {
    setSelectedTraceId(traceId)
    setSelectedObsCallId(null)
    setSelectedEvaluatorResultId(null)
    const next = new URLSearchParams(searchParams)
    next.set('trace', traceId)
    next.delete('result')
    next.delete('obs')
    setSearchParams(next, { replace: true })
  }

  const openObsCall = (callShortId: string) => {
    setSelectedObsCallId(callShortId)
    setSelectedTraceId(null)
    setSelectedEvaluatorResultId(null)
    const next = new URLSearchParams(searchParams)
    next.set('obs', callShortId)
    next.delete('trace')
    next.delete('result')
    setSearchParams(next, { replace: true })
  }

  const closeTrace = () => {
    setSelectedTraceId(null)
    const next = new URLSearchParams(searchParams)
    next.delete('trace')
    setSearchParams(next, { replace: true })
  }

  const closeObsCall = () => {
    setSelectedObsCallId(null)
    const next = new URLSearchParams(searchParams)
    next.delete('obs')
    setSearchParams(next, { replace: true })
  }

  const closeEvaluatorResult = () => {
    setSelectedEvaluatorResultId(null)
    const next = new URLSearchParams(searchParams)
    next.delete('result')
    setSearchParams(next, { replace: true })
  }

  const handleRefresh = () => {
    void refetchTraces()
    void refetchObsCalls()
    void queryClient.invalidateQueries({ queryKey: ['observability-traces'] })
    void queryClient.invalidateQueries({ queryKey: ['observability-calls'] })
  }

  useEffect(() => {
    if (prevWorkspaceRef.current !== null && prevWorkspaceRef.current !== activeWorkspaceId) {
      setPage(0)
      setSelectedTraceId(null)
      setSelectedObsCallId(null)
      setSelectedEvaluatorResultId(null)
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.delete('trace')
          next.delete('result')
          next.delete('obs')
          return next
        },
        { replace: true },
      )
    }
    prevWorkspaceRef.current = activeWorkspaceId
  }, [activeWorkspaceId, setSearchParams])

  useEffect(() => {
    if (traceFromUrl) {
      setSelectedTraceId(traceFromUrl)
      setSelectedObsCallId(null)
      setSelectedEvaluatorResultId(null)
      return
    }
    if (obsFromUrl) {
      setSelectedObsCallId(obsFromUrl)
      setSelectedTraceId(null)
      setSelectedEvaluatorResultId(null)
      return
    }
    if (resultFromUrl) {
      setSelectedEvaluatorResultId(resultFromUrl)
      setSelectedTraceId(null)
      setSelectedObsCallId(null)
    }
  }, [resultFromUrl, traceFromUrl, obsFromUrl])

  const isListLoading =
    (showPipelineRows && loadingList && !listData) ||
    (showProviderRows && loadingObsCalls && productionObsCalls.length === 0)

  const lastUpdatedLabel =
    dataUpdatedAt > 0 ? `Updated ${new Date(dataUpdatedAt).toLocaleTimeString()}` : null

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Calls</h1>
          <p className="mt-2 text-sm text-gray-600">
            Voice agent calls and session traces for your workspace
          </p>
        </div>
        {tab === 'runs' && (
          <Button
            variant="outline"
            onClick={handleRefresh}
            disabled={fetchingList || fetchingObsCalls}
          >
            <RefreshCw
              className={`w-4 h-4 mr-2 ${fetchingList || fetchingObsCalls ? 'animate-spin' : ''}`}
            />
            Refresh
          </Button>
        )}
      </div>

      <div className="flex gap-1 border-b border-gray-200">
        <button
          type="button"
          onClick={() => setTab('runs')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
            tab === 'runs'
              ? 'border-primary-600 text-primary-700'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <Activity className="w-4 h-4 inline mr-1.5 -mt-0.5" />
          Calls
        </button>
        <button
          type="button"
          onClick={() => setTab('setup')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
            tab === 'setup'
              ? 'border-primary-600 text-primary-700'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <BookOpen className="w-4 h-4 inline mr-1.5 -mt-0.5" />
          Connect Pipecat
        </button>
      </div>

      {tab === 'setup' && (
        <div className="bg-white shadow rounded-lg border border-gray-200 overflow-hidden">
          {loadingSetup && <p className="p-6 text-sm text-gray-500">Loading setup…</p>}
          {setup && (
            <div className="divide-y divide-gray-200">
              <div className="px-6 py-5">
                <h2 className="text-lg font-semibold text-gray-900">Pipecat WebRTC integration</h2>
                <p className="text-sm text-gray-600 mt-1 max-w-2xl">
                  Run your Pipecat agent locally, connect via WebRTC, and traces appear here automatically.
                </p>
              </div>

              {(setup.setup_steps ?? []).length > 0 && (
                <div className="px-6 py-5 space-y-3">
                  <h3 className="text-sm font-semibold text-gray-900">Quick start</h3>
                  <ol className="list-decimal list-inside space-y-2 text-sm text-gray-700">
                    {(setup.setup_steps as Array<{ title: string; detail: string }>).map((step) => (
                      <li key={step.title}>
                        <span className="font-medium text-gray-900">{step.title}</span>
                        {' — '}
                        {step.detail}
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              <div className="px-6 py-5 bg-gray-50 space-y-3">
                <h3 className="text-sm font-semibold text-gray-900">Workspace settings</h3>
                <div className="rounded-lg border border-gray-200 bg-white p-4">
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <p className="text-xs font-medium text-gray-500">OTLP export URL</p>
                    <CopyButton text={setup.otlp_endpoint} label="Copy export URL" />
                  </div>
                  <p className="font-mono text-xs text-gray-800 break-all">{setup.otlp_endpoint}</p>
                </div>
                {envBlock && (
                  <div className="rounded-lg border border-gray-200 bg-white p-4">
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <p className="text-xs font-medium text-gray-500">Environment variables</p>
                      <CopyButton text={envBlock} label="Copy env block" />
                    </div>
                    <pre className="text-xs font-mono text-gray-800 whitespace-pre-wrap">{envBlock}</pre>
                  </div>
                )}
              </div>

              {setup.pipecat_python_example && (
                <div className="px-6 py-5 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold text-gray-900">Tracing snippet</h3>
                    <CopyButton text={setup.pipecat_python_example} label="Copy code" />
                  </div>
                  <pre className="text-xs font-mono bg-slate-900 text-slate-100 p-4 rounded-lg overflow-x-auto max-h-80">
                    {setup.pipecat_python_example}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {tab === 'runs' && !activeWorkspaceId && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-6 py-8 text-center text-sm text-amber-900">
          Select a workspace to view calls.
        </div>
      )}

      {tab === 'runs' && activeWorkspaceId && (
        <>
          {(traces.length > 0 || productionObsCalls.length > 0) && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="rounded-lg border border-primary-400 bg-primary-50/40 px-4 py-3 shadow-sm">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-primary-800/70">Total</p>
                <p className="text-2xl font-semibold text-gray-900 tabular-nums mt-0.5">
                  {totalCount + providerSummary.total}
                </p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Open</p>
                <p className="text-2xl font-semibold text-gray-900 tabular-nums mt-0.5">{summaryStats.open}</p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Closed</p>
                <p className="text-2xl font-semibold text-gray-900 tabular-nums mt-0.5">{summaryStats.closed}</p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Live</p>
                <p className="text-2xl font-semibold text-sky-600 tabular-nums mt-0.5">
                  {providerSummary.live}
                </p>
              </div>
            </div>
          )}

          <div className="bg-white shadow rounded-lg overflow-hidden border border-gray-200">
            <div className="px-6 py-4 border-b border-gray-200 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div className="flex items-center gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                  <PhoneCall className="h-5 w-5 text-gray-500" />
                  <h2 className="text-lg font-semibold text-gray-900">All calls</h2>
                </div>
                <div className="flex items-center gap-1">
                  {(
                    [
                      { key: 'all' as const, label: 'Any status' },
                      { key: 'open' as const, label: 'Open' },
                      { key: 'closed' as const, label: 'Closed' },
                    ] as const
                  ).map(({ key, label }) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => {
                        setStatusFilter(key)
                        setPage(0)
                      }}
                      className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                        statusFilter === key
                          ? 'bg-gray-200 text-gray-800 border border-gray-300'
                          : 'text-gray-600 hover:bg-gray-100 border border-transparent'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {productionObsCalls.length > 0 && (
                  <div className="flex items-center gap-1">
                    {(
                      [
                        { key: 'all' as const, label: 'All', count: eventSummary.total },
                        { key: 'call_ended' as const, label: 'Ended', count: eventSummary.ended },
                        { key: 'call_started' as const, label: 'Started', count: eventSummary.started },
                        { key: 'other' as const, label: 'Other', count: eventSummary.other },
                      ] as const
                    ).map(({ key, label, count }) => (
                      <button
                        key={key}
                        type="button"
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
              <div className="flex items-center gap-3">
                <input
                  type="search"
                  placeholder="Search call ID…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 w-40 sm:w-48 focus:ring-primary-500 focus:border-primary-500"
                />
                {lastUpdatedLabel && (
                  <span className="text-xs text-gray-500 hidden sm:inline">{lastUpdatedLabel}</span>
                )}
              </div>
            </div>

            {isListLoading && (
              <div className="p-12 text-center">
                <Loader className="w-6 h-6 text-primary-500 animate-spin mx-auto mb-3" />
                <p className="text-sm text-gray-500">Loading calls…</p>
              </div>
            )}

            {listErrorMessage && showPipelineRows && (
              <div className="p-4 text-sm text-red-800 bg-red-50 border-b border-red-100">
                Could not load traces: {listErrorMessage}
              </div>
            )}

            {!isListLoading && !hasListRows && !listError && (
              <div className="p-12 text-center text-sm text-gray-600">
                <p className="font-medium text-gray-900 mb-1">No calls yet</p>
                <p className="mb-4">Run a voice agent session to see calls here.</p>
                <button
                  type="button"
                  onClick={() => setTab('setup')}
                  className="text-primary-600 hover:text-primary-800 font-medium"
                >
                  Connect Pipecat →
                </button>
              </div>
            )}

            {hasListRows && (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Call ID
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Status
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Platform
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Details
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Started
                      </th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {showProviderRows &&
                      filteredObsCalls.map((call) => (
                        <tr
                          key={`obs-${call.id}`}
                          className={`transition-colors cursor-pointer ${
                            selectedObsCallId === call.call_short_id
                              ? 'bg-primary-50/60 hover:bg-primary-50/80'
                              : 'hover:bg-gray-50'
                          }`}
                          onClick={() => openObsCall(call.call_short_id)}
                        >
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className="font-mono font-semibold text-primary-600">
                              #{call.call_short_id}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <EventBadge event={call.call_event ?? undefined} />
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <PlatformBadge platform={call.provider_platform ?? undefined} />
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                            <CallAgentLink agent={call.agent} />
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            <span title={call.created_at ? formatWhen(call.created_at) : undefined}>
                              {call.created_at ? formatRelative(call.created_at) : '—'}
                            </span>
                          </td>
                          <td
                            className="px-6 py-4 whitespace-nowrap text-right"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <div className="flex items-center justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => openObsCall(call.call_short_id)}
                                leftIcon={<Eye className="w-4 h-4" />}
                              >
                                View
                              </Button>
                              <button
                                type="button"
                                onClick={() => setDeleteObsCallId(call.call_short_id)}
                                className="rounded-lg p-1.5 text-gray-400 hover:bg-rose-50 hover:text-rose-600"
                                aria-label="Delete call"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}

                    {showPipelineRows &&
                      filteredTraces.map((trace: {
                        id: string
                        call_short_id?: string
                        transport?: string
                        status: string
                        failure_flags?: string[]
                        turn_count: number
                        response_latency_p50_ms?: number | null
                        started_at: string
                      }) => (
                        <tr
                          key={`trace-${trace.id}`}
                          className={`transition-colors cursor-pointer ${
                            selectedTraceId === trace.id
                              ? 'bg-primary-50/60 hover:bg-primary-50/80'
                              : 'hover:bg-gray-50'
                          }`}
                          onClick={() => openTrace(trace.id)}
                        >
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className="font-mono font-semibold text-primary-600">
                              #{trace.call_short_id || trace.id.slice(0, 8)}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="flex flex-col gap-1">
                              <StatusLabel status={trace.status} />
                              {trace.failure_flags?.map((flag) => (
                                <span
                                  key={flag}
                                  className="inline-flex w-fit rounded-md border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-800"
                                >
                                  {FAILURE_FLAG_LABELS[flag] ?? flag}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700 capitalize">
                            {trace.transport ?? 'webrtc'}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700 tabular-nums">
                            {trace.turn_count} turns
                            {trace.response_latency_p50_ms != null
                              ? ` · ${Math.round(trace.response_latency_p50_ms)} ms p50`
                              : ''}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            <span title={formatWhen(trace.started_at)}>
                              {formatRelative(trace.started_at)}
                            </span>
                          </td>
                          <td
                            className="px-6 py-4 whitespace-nowrap text-right"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => openTrace(trace.id)}
                              leftIcon={<Eye className="w-4 h-4" />}
                            >
                              View
                            </Button>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}

            {showPipelineRows && totalPages > 1 && filteredTraces.length > 0 && (
              <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between text-sm">
                <p className="text-gray-500">
                  Page {page + 1} of {totalPages} · {totalCount} sessions
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 0}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page >= totalPages - 1}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}

            {hasListRows &&
              showPipelineRows &&
              traces.length > 0 &&
              filteredTraces.length === 0 &&
              showProviderRows &&
              filteredObsCalls.length === 0 && (
                <div className="p-12 text-center text-sm text-gray-500">
                  No rows match your search.{' '}
                  <button
                    type="button"
                    onClick={() => setSearchQuery('')}
                    className="text-primary-600 font-medium"
                  >
                    Clear search
                  </button>
                </div>
              )}
          </div>

          <ConfirmModal
            title="Delete call"
            description="This will permanently remove this provider call record."
            isOpen={Boolean(deleteObsCallId)}
            isLoading={deleteObsMutation.isPending}
            onCancel={() => setDeleteObsCallId(null)}
            onConfirm={() => deleteObsCallId && deleteObsMutation.mutate(deleteObsCallId)}
          />
        </>
      )}

      <TraceDetailDrawer
        traceId={selectedTraceId}
        observabilityCallShortId={selectedObsCallId}
        evaluatorResultId={selectedEvaluatorResultId}
        open={Boolean(selectedTraceId || selectedObsCallId || selectedEvaluatorResultId)}
        onClose={() => {
          if (selectedTraceId) closeTrace()
          if (selectedObsCallId) closeObsCall()
          if (selectedEvaluatorResultId) closeEvaluatorResult()
        }}
      />
    </div>
  )
}
