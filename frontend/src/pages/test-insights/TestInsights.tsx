import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Eye, Loader, PhoneCall, RefreshCw, Trash2 } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import TableListPagination from '../../components/TableListPagination'
import TraceDetailDrawer from '../../components/call-recordings/TraceDetailDrawer'
import { CallAgentLink } from '../observability/CallAgentLink'
import type { ObservabilityCallAgent } from '../../types/api'
import { CallSourceBadge, EventBadge, PlatformBadge } from '../observability/observabilityCallUi'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { itemsOf } from '../../lib/safeData'
type StatusFilter = 'all' | 'open' | 'closed'
type EventFilter = 'all' | 'call_ended' | 'call_started' | 'other'

const PAGE_SIZE = 15

type CallsHubRow = {
  kind: 'obs' | 'trace'
  sort_at?: string | null
  obs?: {
    id: string
    call_short_id: string
    call_event?: string | null
    provider_platform?: string | null
    created_at?: string | null
    agent?: ObservabilityCallAgent | null
  }
  trace?: SyntheticTraceRow
}

type SyntheticTraceRow = {
  id: string
  call_short_id?: string
  transport?: string
  status: string
  turn_count: number
  span_count?: number
  derive_pending?: boolean
  started_at: string
}

const callsHubQueryKey = (
  workspaceId: string | null,
  page: number,
  status: StatusFilter,
  event: EventFilter,
  search: string,
) => ['calls-hub', workspaceId, page, status, event, search] as const

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
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(traceFromUrl)
  const [selectedObsCallId, setSelectedObsCallId] = useState<string | null>(obsFromUrl)
  const [selectedEvaluatorResultId, setSelectedEvaluatorResultId] = useState<string | null>(resultFromUrl)
  const [deleteObsCallId, setDeleteObsCallId] = useState<string | null>(null)
  const [deleteTraceId, setDeleteTraceId] = useState<string | null>(null)
  const [callsPage, setCallsPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [eventFilter, setEventFilter] = useState<EventFilter>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const prevWorkspaceRef = useRef<string | null>(null)

  const apiStatus = statusFilter === 'all' ? undefined : statusFilter
  const hubSkip = (callsPage - 1) * PAGE_SIZE

  const {
    data: hubData,
    isLoading: loadingHub,
    isFetching: fetchingHub,
    isError: listError,
    error: listErrorDetail,
    refetch: refetchHub,
    dataUpdatedAt,
  } = useQuery({
    queryKey: callsHubQueryKey(
      activeWorkspaceId,
      callsPage,
      statusFilter,
      eventFilter,
      searchQuery.trim(),
    ),
    queryFn: () =>
      apiClient.listCallsHub({
        skip: hubSkip,
        limit: PAGE_SIZE,
        status: apiStatus,
        search: searchQuery.trim() || undefined,
        event: eventFilter,
      }),
    enabled: Boolean(activeWorkspaceId),
    retry: false,
    staleTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const live = query.state.data?.summary?.obs_live ?? 0
      return live > 0 ? 3000 : false
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
      void queryClient.invalidateQueries({ queryKey: ['calls-hub'] })
    },
  })

  const deleteTraceMutation = useMutation({
    mutationFn: (traceId: string) => apiClient.deleteSyntheticCallTrace(traceId),
    onSuccess: (_data, traceId) => {
      setDeleteTraceId(null)
      setSelectedTraceId((current) => (current === traceId ? null : current))
      const next = new URLSearchParams(searchParams)
      if (next.get('trace') === traceId) {
        next.delete('trace')
        setSearchParams(next, { replace: true })
      }
      void queryClient.invalidateQueries({ queryKey: ['calls-hub'] })
    },
  })

  const hubItems = itemsOf<CallsHubRow>(hubData)
  const hubSummary = hubData?.summary
  const hubTotal = hubData?.total ?? 0
  const hubPage = hubData?.page ?? callsPage
  const hubPageCount = hubData?.page_count ?? 1

  const eventSummary = useMemo(
    () => ({
      total: hubSummary?.obs_total ?? 0,
      ended: hubSummary?.obs_ended ?? 0,
      started: hubSummary?.obs_started ?? 0,
      other: hubSummary?.obs_other ?? 0,
    }),
    [hubSummary],
  )

  const hasWorkspaceCalls = (hubSummary?.total ?? 0) > 0

  const listErrorMessage =
    listError && listErrorDetail instanceof Error
      ? listErrorDetail.message
      : listError
        ? 'Could not load traces'
        : null

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
    void refetchHub()
    void queryClient.invalidateQueries({ queryKey: ['calls-hub'] })
  }

  useEffect(() => {
    if (prevWorkspaceRef.current !== null && prevWorkspaceRef.current !== activeWorkspaceId) {
      setCallsPage(1)
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

  useEffect(() => {
    setCallsPage(1)
  }, [statusFilter, eventFilter, searchQuery, activeWorkspaceId])

  const isListLoading = loadingHub && hubItems.length === 0
  const isListRefreshing = fetchingHub && hubItems.length > 0

  const lastUpdatedLabel =
    dataUpdatedAt > 0 ? `Updated ${new Date(dataUpdatedAt).toLocaleTimeString()}` : null

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Calls</h1>
          <p className="mt-2 text-sm text-gray-600 max-w-2xl">
            One list for production webhook calls and pipeline traces. Webhook rows show provider telephony;
            pipeline rows show OTLP timing (WebRTC) or phone-eval turn timing—open a row to see what applies.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={handleRefresh}
          disabled={fetchingHub}
        >
          <RefreshCw className={`mr-2 h-4 w-4 ${fetchingHub ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {!activeWorkspaceId && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-6 py-8 text-center text-sm text-amber-900">
          Select a workspace to view calls.
        </div>
      )}

      {activeWorkspaceId && (
        <>
          {hasWorkspaceCalls && hubSummary && (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-primary-400 bg-primary-50/40 px-4 py-3 shadow-sm">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-primary-800/70">
                  Total
                </p>
                <p className="mt-0.5 text-2xl font-semibold tabular-nums text-gray-900">
                  {hubSummary?.total ?? 0}
                </p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Open</p>
                <p className="mt-0.5 text-2xl font-semibold tabular-nums text-gray-900">
                  {hubSummary?.traces_open ?? 0}
                </p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                  Closed
                </p>
                <p className="mt-0.5 text-2xl font-semibold tabular-nums text-gray-900">
                  {hubSummary?.traces_closed ?? 0}
                </p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Live</p>
                <p className="mt-0.5 text-2xl font-semibold tabular-nums text-sky-600">
                  {hubSummary?.obs_live ?? 0}
                </p>
              </div>
            </div>
          )}

          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow">
            <div className="flex flex-col gap-4 border-b border-gray-200 px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-3">
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
                        setCallsPage(1)
                      }}
                      className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                        statusFilter === key
                          ? 'border-gray-300 bg-gray-200 text-gray-800'
                          : 'border-transparent text-gray-600 hover:bg-gray-100'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {(hubSummary?.obs_total ?? 0) > 0 && (
                  <div className="flex items-center gap-1">
                    {(
                      [
                        { key: 'all' as const, label: 'All events', count: eventSummary.total },
                        { key: 'call_ended' as const, label: 'Ended', count: eventSummary.ended },
                        { key: 'call_started' as const, label: 'Started', count: eventSummary.started },
                        { key: 'other' as const, label: 'Other', count: eventSummary.other },
                      ] as const
                    ).map(({ key, label, count }) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setEventFilter(key)}
                        className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                          eventFilter === key
                            ? 'border-primary-300 bg-primary-100 text-primary-800'
                            : 'border-transparent text-gray-600 hover:bg-gray-100'
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
                  className="w-40 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:ring-primary-500 sm:w-48"
                />
                {lastUpdatedLabel && (
                  <span className="hidden text-xs text-gray-500 sm:inline">{lastUpdatedLabel}</span>
                )}
              </div>
            </div>

            {isListLoading && (
              <div className="p-12 text-center">
                <Loader className="w-6 h-6 text-primary-500 animate-spin mx-auto mb-3" />
                <p className="text-sm text-gray-500">Loading calls…</p>
              </div>
            )}

            {isListRefreshing && !isListLoading && (
              <div className="flex items-center justify-center gap-2 border-b border-gray-100 bg-gray-50/80 px-4 py-2 text-xs text-gray-500">
                <Loader className="h-3.5 w-3.5 animate-spin text-primary-500" />
                Refreshing calls…
              </div>
            )}

            {listErrorMessage && (
              <div className="border-b border-red-100 bg-red-50 p-4 text-sm text-red-800">
                Could not load calls: {listErrorMessage}
              </div>
            )}

            {!isListLoading && !hasWorkspaceCalls && !listError && (
              <div className="p-12 text-center text-sm text-gray-600">
                <p className="mb-1 font-medium text-gray-900">No calls yet</p>
                <p>Connect a voice agent with pipeline tracing or a production webhook to see calls here.</p>
              </div>
            )}

            {!isListLoading && hubItems.length > 0 && (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                        Call ID
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                        Source
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                        Status
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                        Platform
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                        Summary
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
                    {hubItems.map((row) => {
                      if (row.kind === 'obs' && row.obs) {
                        const call = row.obs
                        return (
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
                            <CallSourceBadge source="telephony" />
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
                        )
                      }

                      const trace = row.trace as SyntheticTraceRow | undefined
                      if (!trace?.id) return null
                      return (
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
                            <CallSourceBadge source="otlp" />
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <StatusLabel status={trace.status} />
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700 capitalize">
                            {trace.transport ?? 'webrtc'}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700 tabular-nums">
                            {trace.status === 'open' &&
                            trace.turn_count < 1 &&
                            (trace.derive_pending || (trace.span_count ?? 0) > 0)
                              ? 'Processing spans…'
                              : `${trace.turn_count} turns`}
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
                            <div className="flex items-center justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => openTrace(trace.id)}
                                leftIcon={<Eye className="w-4 h-4" />}
                              >
                                View
                              </Button>
                              <button
                                type="button"
                                onClick={() => setDeleteTraceId(trace.id)}
                                className="rounded-lg p-1.5 text-gray-400 hover:bg-rose-50 hover:text-rose-600"
                                aria-label="Delete call trace"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {hubTotal > 0 && (
              <TableListPagination
                page={hubPage}
                pageCount={hubPageCount}
                total={hubTotal}
                pageSize={PAGE_SIZE}
                onPrev={() => setCallsPage((p) => Math.max(1, p - 1))}
                onNext={() => setCallsPage((p) => Math.min(hubPageCount, p + 1))}
              />
            )}

            {!isListLoading && hasWorkspaceCalls && hubTotal === 0 && (
              <div className="p-12 text-center text-sm text-gray-500">
                No rows match your filters.{' '}
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery('')
                    setStatusFilter('all')
                    setEventFilter('all')
                  }}
                  className="text-primary-600 font-medium"
                >
                  Clear filters
                </button>
              </div>
            )}
          </div>

          <ConfirmModal
            title="Delete call"
            description="Permanently removes this webhook call record from observability."
            isOpen={Boolean(deleteObsCallId)}
            isLoading={deleteObsMutation.isPending}
            onCancel={() => setDeleteObsCallId(null)}
            onConfirm={() => deleteObsCallId && deleteObsMutation.mutate(deleteObsCallId)}
          />

          <ConfirmModal
            title="Delete call trace"
            description="Permanently removes this pipeline trace and its timing data from observability."
            isOpen={Boolean(deleteTraceId)}
            isLoading={deleteTraceMutation.isPending}
            onCancel={() => setDeleteTraceId(null)}
            onConfirm={() => deleteTraceId && deleteTraceMutation.mutate(deleteTraceId)}
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
