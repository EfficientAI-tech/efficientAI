import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  Activity,
  BookOpen,
  Check,
  Copy,
  Eye,
  Globe,
  RefreshCw,
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import SyntheticCallTracePanel from '../../components/call-recordings/SyntheticCallTracePanel'
import Button from '../../components/Button'
import { useWorkspaceStore } from '../../store/workspaceStore'

type Tab = 'runs' | 'setup'

const tracesQueryKey = (workspaceId: string | null) =>
  ['observability-traces', workspaceId] as const

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
      className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800"
      title={label ?? 'Copy'}
    >
      {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function StatusBadge({ status }: { status: string }) {
  const open = status === 'open'
  const label = status === 'finalized' ? 'closed' : status
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-medium rounded-full px-2.5 py-0.5 capitalize ${
        open
          ? 'bg-amber-50 text-amber-700 border border-amber-200'
          : 'bg-emerald-50 text-emerald-700 border border-emerald-200'
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${open ? 'bg-amber-500 animate-pulse' : 'bg-emerald-500'}`} />
      {label}
    </span>
  )
}

function TransportBadge({ transport }: { transport?: string }) {
  const t = (transport || 'webrtc').toLowerCase()
  if (t !== 'webrtc') {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-medium rounded-md px-2 py-0.5 border bg-gray-50 text-gray-600 border-gray-100 capitalize">
        {t}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium rounded-md px-2 py-0.5 border bg-blue-50 text-blue-700 border-blue-100">
      <Globe className="w-3 h-3" />
      WebRTC
    </span>
  )
}

function TraceDetailShell({
  traceId,
  onClose,
  layout,
}: {
  traceId: string
  onClose: () => void
  layout: 'desktop' | 'mobile'
}) {
  useEffect(() => {
    if (layout !== 'mobile') return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [layout, onClose])

  if (layout === 'mobile') {
    return (
      <>
        <button
          type="button"
          className="fixed inset-0 z-40 bg-gray-900/50 backdrop-blur-[1px]"
          aria-label="Close trace detail"
          onClick={onClose}
        />
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Call trace detail"
          className="fixed inset-y-0 right-0 z-50 w-full max-w-lg bg-white shadow-2xl flex flex-col border-l border-gray-200"
        >
          <SyntheticCallTracePanel traceId={traceId} onClose={onClose} />
        </div>
      </>
    )
  }

  return (
    <div className="flex flex-1 min-w-0 min-h-[calc(100vh-11rem)] rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <SyntheticCallTracePanel traceId={traceId} onClose={onClose} />
    </div>
  )
}

export default function TestInsights() {
  const queryClient = useQueryClient()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const [searchParams, setSearchParams] = useSearchParams()
  const resultFromUrl = searchParams.get('result')
  const traceFromUrl = searchParams.get('trace')
  const [tab, setTab] = useState<Tab>('runs')
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(traceFromUrl)
  const prevWorkspaceRef = useRef<string | null>(null)
  const [isMobileView, setIsMobileView] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia('(max-width: 1023px)').matches : false,
  )

  const {
    data: listData,
    isLoading: loadingList,
    isFetching: fetchingList,
    isError: listError,
    error: listErrorDetail,
    refetch: refetchTraces,
    dataUpdatedAt,
  } = useQuery({
    queryKey: tracesQueryKey(activeWorkspaceId),
    queryFn: () => apiClient.listSyntheticCallTraces({ limit: 100 }),
    enabled: tab === 'runs' && Boolean(activeWorkspaceId),
    retry: false,
    refetchOnWindowFocus: true,
    staleTime: 30_000,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      const hasOpen = items.some((t: { status?: string }) => t.status === 'open')
      return hasOpen ? 15_000 : false
    },
  })

  const { data: setup, isLoading: loadingSetup } = useQuery({
    queryKey: ['synthetic-call-trace-setup'],
    queryFn: () => apiClient.getSyntheticCallTraceSetup(),
    enabled: tab === 'setup',
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  const traces = listData?.items ?? []
  const listErrorMessage =
    listError && listErrorDetail instanceof Error
      ? listErrorDetail.message
      : listError
        ? 'Could not load traces'
        : null

  const openTraces = traces.filter((t: any) => t.status === 'open').length
  const withLatency = traces.filter((t: any) => t.response_latency_p50_ms != null).length

  const envBlock = setup?.one_time_env_vars
    ? Object.entries(setup.one_time_env_vars)
        .map(([k, v]) => `${k}=${v}`)
        .join('\n')
    : ''

  const openTrace = (traceId: string) => {
    setSelectedTraceId(traceId)
    const next = new URLSearchParams(searchParams)
    next.set('trace', traceId)
    next.delete('result')
    setSearchParams(next, { replace: true })
  }

  const closeTrace = () => {
    setSelectedTraceId(null)
    const next = new URLSearchParams(searchParams)
    next.delete('trace')
    next.delete('result')
    setSearchParams(next, { replace: true })
  }

  const handleRefresh = () => {
    void refetchTraces()
    if (selectedTraceId) {
      void queryClient.invalidateQueries({
        queryKey: ['synthetic-call-trace', selectedTraceId, 'by-trace'],
      })
    }
  }

  useEffect(() => {
    if (prevWorkspaceRef.current !== null && prevWorkspaceRef.current !== activeWorkspaceId) {
      setSelectedTraceId(null)
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.delete('trace')
          next.delete('result')
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
      return
    }
    if (!resultFromUrl) return
    let cancelled = false
    apiClient
      .getSyntheticCallTraceForResult(resultFromUrl)
      .then((trace) => {
        if (!cancelled && trace?.id) {
          setSelectedTraceId(trace.id)
          setSearchParams(
            (prev) => {
              const next = new URLSearchParams(prev)
              next.set('trace', trace.id)
              next.delete('result')
              return next
            },
            { replace: true },
          )
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [resultFromUrl, traceFromUrl, setSearchParams])

  const drawerOpen = Boolean(selectedTraceId)

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 1023px)')
    const onChange = () => setIsMobileView(mq.matches)
    onChange()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    if (!drawerOpen || !isMobileView) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [drawerOpen, isMobileView])

  const lastUpdatedLabel =
    dataUpdatedAt > 0 ? `Updated ${new Date(dataUpdatedAt).toLocaleTimeString()}` : null

  const totalCount = listData?.total ?? traces.length
  const showingPartial = totalCount > traces.length

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Call Traces</h1>
          <p className="mt-1 text-sm text-gray-600 max-w-2xl leading-relaxed">
            See how fast your voice agent responds on each turn — speech recognition, model, and
            text-to-speech timing from a local Pipecat WebRTC call.
          </p>
        </div>
        {tab === 'runs' && (
          <button
            type="button"
            onClick={handleRefresh}
            disabled={fetchingList}
            className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg shadow-sm hover:bg-gray-50 disabled:opacity-50 shrink-0"
          >
            <RefreshCw className={`w-4 h-4 ${fetchingList ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        )}
      </div>

      <div className="flex gap-1 border-b border-gray-200">
        <button
          type="button"
          onClick={() => setTab('runs')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
            tab === 'runs'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <Activity className="w-4 h-4 inline mr-1.5 -mt-0.5" />
          Traces
        </button>
        <button
          type="button"
          onClick={() => setTab('setup')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
            tab === 'setup'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <BookOpen className="w-4 h-4 inline mr-1.5 -mt-0.5" />
          Connect Pipecat
        </button>
      </div>

      {tab === 'setup' && (
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          {loadingSetup && <p className="p-6 text-sm text-gray-500">Loading setup…</p>}
          {setup && (
            <div className="divide-y divide-gray-100">
              <div className="p-6 bg-gradient-to-br from-indigo-50/80 to-white">
                <h2 className="text-lg font-semibold text-gray-900">Local Pipecat WebRTC</h2>
                <p className="text-sm text-gray-600 mt-1 max-w-2xl">
                  Run your Pipecat agent on your machine, talk in the browser, and traces show up
                  here automatically. Full example:{' '}
                  <code className="text-xs bg-white/80 px-1.5 py-0.5 rounded border border-gray-200">
                    docs/examples/pipecat_multi_agent_webrtc_tracing.py
                  </code>
                </p>
              </div>

              {(setup.setup_steps ?? []).length > 0 && (
                <div className="p-6 space-y-4">
                  <h3 className="text-sm font-semibold text-gray-900">Quick start</h3>
                  <ol className="space-y-4">
                    {(setup.setup_steps as Array<{ title: string; detail: string }>).map(
                      (step, idx) => (
                        <li key={step.title} className="flex gap-4">
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-xs font-bold text-white">
                            {idx + 1}
                          </span>
                          <div>
                            <p className="text-sm font-medium text-gray-900">{step.title}</p>
                            <p className="text-sm text-gray-600 mt-0.5 leading-relaxed">{step.detail}</p>
                          </div>
                        </li>
                      ),
                    )}
                  </ol>
                </div>
              )}

              <div className="p-6 space-y-4 bg-gray-50/50">
                <h3 className="text-sm font-semibold text-gray-900">Your workspace settings</h3>
                <div className="space-y-3">
                  <div className="rounded-lg border border-gray-200 bg-white p-4">
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <p className="text-xs font-medium text-gray-500">Trace export URL</p>
                      <CopyButton text={setup.otlp_endpoint} label="Copy export URL" />
                    </div>
                    <p className="font-mono text-xs text-gray-800 break-all">{setup.otlp_endpoint}</p>
                  </div>
                  {envBlock && (
                    <div className="rounded-lg border border-gray-200 bg-white p-4">
                      <div className="flex items-center justify-between gap-2 mb-2">
                        <p className="text-xs font-medium text-gray-500">Add to Pipecat .env</p>
                        <CopyButton text={envBlock} label="Copy env block" />
                      </div>
                      <pre className="text-xs font-mono text-gray-800 whitespace-pre-wrap">{envBlock}</pre>
                    </div>
                  )}
                </div>
                {setup.per_call_correlation?.note && (
                  <p className="text-sm text-gray-600 leading-relaxed">{setup.per_call_correlation.note}</p>
                )}
              </div>

              {setup.pipecat_python_example && (
                <div className="p-6 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold text-gray-900">Tracing snippet for bot.py</h3>
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
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-6 py-8 text-center text-sm text-amber-900">
          Select a workspace to view call traces.
        </div>
      )}

      {tab === 'runs' && activeWorkspaceId && (
        <div className="flex flex-col lg:flex-row gap-4 lg:gap-6 lg:items-start">
          <div className={`min-w-0 ${selectedTraceId ? 'lg:w-[44%] lg:shrink-0' : 'w-full'}`}>
            {traces.length > 0 && (
              <div className="grid grid-cols-3 gap-3 mb-4">
                <div className="rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Total</p>
                  <p className="text-2xl font-semibold text-gray-900 tabular-nums">{totalCount}</p>
                  {showingPartial && (
                    <p className="text-[10px] text-gray-400 mt-0.5">Showing {traces.length}</p>
                  )}
                </div>
                <div className="rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">In progress</p>
                  <p className="text-2xl font-semibold text-amber-600 tabular-nums">{openTraces}</p>
                </div>
                <div className="rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">With timing</p>
                  <p className="text-2xl font-semibold text-indigo-600 tabular-nums">{withLatency}</p>
                </div>
              </div>
            )}

            <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-100 bg-gradient-to-r from-gray-50 to-white flex justify-between items-center gap-2">
                <div>
                  <h2 className="text-sm font-semibold text-gray-900">Recent calls</h2>
                  {lastUpdatedLabel && (
                    <p className="text-xs text-gray-500 mt-0.5">{lastUpdatedLabel}</p>
                  )}
                </div>
              </div>

              {loadingList && !listData && (
                <p className="p-10 text-sm text-gray-500 text-center">Loading traces…</p>
              )}

              {listErrorMessage && (
                <div className="p-4 text-sm text-red-800 bg-red-50 border-b border-red-100 space-y-2">
                  <p>Could not load traces: {listErrorMessage}</p>
                  <button
                    type="button"
                    onClick={() => refetchTraces()}
                    className="text-xs font-medium text-red-900 underline"
                  >
                    Retry
                  </button>
                </div>
              )}

              {!loadingList && !listError && activeWorkspaceId && traces.length === 0 && (
                <div className="p-12 text-center text-sm text-gray-600 space-y-4">
                  <div className="w-12 h-12 rounded-full bg-indigo-50 flex items-center justify-center mx-auto">
                    <Activity className="w-6 h-6 text-indigo-400" />
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">No calls traced yet</p>
                    <p className="mt-1 max-w-sm mx-auto">
                      Connect your Pipecat agent, run a short WebRTC call at{' '}
                      <code className="text-xs bg-gray-100 px-1 rounded">localhost:7860/client</code>,
                      then refresh this list.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setTab('setup')}
                    className="text-indigo-600 hover:text-indigo-800 text-sm font-medium"
                  >
                    Connect Pipecat →
                  </button>
                </div>
              )}

              {traces.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-100">
                    <thead>
                      <tr className="bg-gray-50/80">
                        <th className="px-4 py-3 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                          Call ID
                        </th>
                        <th className="px-4 py-3 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                          Type
                        </th>
                        <th className="px-4 py-3 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                          Status
                        </th>
                        <th className="px-4 py-3 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                          Turns
                        </th>
                        <th className="px-4 py-3 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                          Median
                        </th>
                        <th className="px-4 py-3 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                          When
                        </th>
                        <th className="px-4 py-3" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {traces.map((trace: any) => {
                        const selected = selectedTraceId === trace.id
                        return (
                          <tr
                            key={trace.id}
                            role="button"
                            tabIndex={0}
                            className={`cursor-pointer transition-colors ${
                              selected
                                ? 'bg-indigo-50/70 ring-1 ring-inset ring-indigo-200'
                                : 'hover:bg-gray-50/80'
                            }`}
                            onClick={() => openTrace(trace.id)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault()
                                openTrace(trace.id)
                              }
                            }}
                          >
                            <td className="px-4 py-3.5 whitespace-nowrap">
                              <span className="font-mono font-semibold text-indigo-600">
                                #{trace.call_short_id || trace.id.slice(0, 8)}
                              </span>
                            </td>
                            <td className="px-4 py-3.5 whitespace-nowrap">
                              <TransportBadge transport={trace.transport} />
                            </td>
                            <td className="px-4 py-3.5 whitespace-nowrap">
                              <StatusBadge status={trace.status} />
                            </td>
                            <td className="px-4 py-3.5 whitespace-nowrap text-sm text-gray-700 tabular-nums font-medium">
                              {trace.turn_count}
                            </td>
                            <td className="px-4 py-3.5 whitespace-nowrap text-sm tabular-nums">
                              {trace.response_latency_p50_ms != null ? (
                                <span className="font-medium text-gray-900">
                                  {Math.round(trace.response_latency_p50_ms)}
                                  <span className="text-gray-400 font-normal ml-0.5">ms</span>
                                </span>
                              ) : (
                                <span className="text-gray-300">—</span>
                              )}
                            </td>
                            <td className="px-4 py-3.5 whitespace-nowrap text-sm text-gray-500">
                              <span title={formatWhen(trace.started_at)}>{formatRelative(trace.started_at)}</span>
                            </td>
                            <td
                              className="px-4 py-3.5 whitespace-nowrap text-right"
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
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {selectedTraceId && !isMobileView && (
            <TraceDetailShell traceId={selectedTraceId} onClose={closeTrace} layout="desktop" />
          )}
        </div>
      )}

      {drawerOpen && selectedTraceId && isMobileView && (
        <TraceDetailShell traceId={selectedTraceId} onClose={closeTrace} layout="mobile" />
      )}
    </div>
  )
}
