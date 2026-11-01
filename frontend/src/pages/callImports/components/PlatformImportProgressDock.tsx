import { useEffect, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation } from 'react-router-dom'
import { useQueries, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Loader2,
  Minus,
  X,
} from 'lucide-react'
import { apiClient } from '../../../lib/api'
import type { CallImport, CallImportListResponse, PlatformImportProgress } from '../../../types/api'
import { usePlatformImportProgressStore } from '../../../store/platformImportProgressStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { platformSkipLines } from '../platformImportLabel'

function phaseLabel(phase: PlatformImportProgress['phase']): string {
  switch (phase) {
    case 'discovering':
      return 'Discovering calls'
    case 'importing':
      return 'Downloading recordings'
    case 'paused':
      return 'Paused'
    case 'stalled':
      return 'Stalled'
    case 'capped':
      return 'Stopped at call cap'
    case 'failed':
      return 'Needs attention'
    case 'deleting':
      return 'Removing'
    case 'complete':
      return 'Complete'
    default:
      return 'Working'
  }
}

function ProgressTrack({
  percent,
  tone = 'primary',
}: {
  percent: number
  tone?: 'primary' | 'amber' | 'green'
}) {
  const bar =
    tone === 'green'
      ? 'bg-green-500'
      : tone === 'amber'
        ? 'bg-amber-500'
        : 'bg-primary-600'
  return (
    <div className="h-1.5 w-full rounded-full bg-gray-200 overflow-hidden">
      <div
        className={`h-full rounded-full transition-all duration-500 ${bar}`}
        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
      />
    </div>
  )
}

function ImportProgressCard({
  progress,
  label,
  onDismiss,
}: {
  progress: PlatformImportProgress
  label: string
  onDismiss: () => void
}) {
  const { discovery, recordings, overall_percent, phase, is_active, skip_counts, paused } = progress
  const skipLines = platformSkipLines(skip_counts)
  const queryClient = useQueryClient()
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['platform-import-progress'] })
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 truncate">{label}</p>
          <p className="text-xs text-gray-500 capitalize">
            {progress.provider || 'platform'}
            {progress.dataset ? ` · ${progress.dataset}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {is_active ? (
            <Loader2 className="h-4 w-4 text-primary-600 animate-spin" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-green-600" />
          )}
          <button
            type="button"
            onClick={onDismiss}
            className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100"
            aria-label="Remove from panel"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="font-medium text-gray-700">{phaseLabel(phase)}</span>
          <span className="tabular-nums text-gray-600">{overall_percent.toFixed(0)}%</span>
        </div>
        <ProgressTrack percent={overall_percent} tone={is_active ? 'primary' : 'green'} />
      </div>

      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div className="rounded-md bg-gray-50 px-2 py-1.5 border border-gray-100">
          <div className="flex justify-between text-gray-500 mb-0.5">
            <span>Discovery</span>
            <span className="tabular-nums">{discovery.percent.toFixed(0)}%</span>
          </div>
          <ProgressTrack percent={discovery.percent} tone="amber" />
          <p className="text-gray-600 mt-1 tabular-nums">
            {discovery.slices_completed}/{discovery.slices_total} windows
            {discovery.slices_running > 0 ? ` · ${discovery.slices_running} listing` : ''}
            {(discovery.slices_queued ?? 0) > 0
              ? ` · ${discovery.slices_queued} queued`
              : ''}
            {discovery.listed_total > 0 ? ` · ${discovery.listed_total} listed` : ''}
          </p>
        </div>
        <div className="rounded-md bg-gray-50 px-2 py-1.5 border border-gray-100">
          <div className="flex justify-between text-gray-500 mb-0.5">
            <span>Recordings</span>
            <span className="tabular-nums">{recordings.percent.toFixed(0)}%</span>
          </div>
          <ProgressTrack percent={recordings.percent} tone="green" />
          <p className="text-gray-600 mt-1 tabular-nums">
            <span className="text-green-700 font-medium">{recordings.completed}</span> done
            {recordings.failed > 0 && (
              <span className="text-red-600"> · {recordings.failed} failed</span>
            )}
            {recordings.processing > 0 && (
              <span> · {recordings.processing} downloading</span>
            )}
            {(recordings.queued ?? 0) > 0 && (
              <span> · {recordings.queued} queued</span>
            )}
            {recordings.pending > (recordings.queued ?? 0) && (
              <span>
                {' '}
                · {recordings.pending - (recordings.queued ?? 0)} waiting
              </span>
            )}
            <span className="text-gray-400"> / {recordings.total}</span>
          </p>
        </div>
      </div>

      {skipLines.length > 0 && (
        <p className="text-[11px] text-gray-500">{skipLines.join(' · ')}</p>
      )}

      <div className="flex gap-2">
        {is_active && !paused && phase !== 'deleting' && (
          <button
            type="button"
            className="text-xs font-medium text-gray-700 hover:text-gray-900"
            onClick={() => {
              void apiClient.callImports.pausePlatformImport(progress.call_import_id).then(refresh)
            }}
          >
            Pause
          </button>
        )}
        {paused && (
          <button
            type="button"
            className="text-xs font-medium text-primary-700 hover:text-primary-800"
            onClick={() => {
              void apiClient.callImports.resumePlatformImport(progress.call_import_id).then(refresh)
            }}
          >
            Resume
          </button>
        )}
        {(phase === 'failed' || (progress.slice_errors ?? 0) > 0) && (
          <button
            type="button"
            className="text-xs font-medium text-amber-700 hover:text-amber-800"
            onClick={() => {
              void apiClient.callImports.retryPlatformDiscovery(progress.call_import_id).then(refresh)
            }}
          >
            Retry discovery
          </button>
        )}
      </div>

      {progress.paused && progress.pause_reason && (
        <p className="text-[11px] text-amber-800 bg-amber-50 rounded px-2 py-1">
          Paused: {progress.pause_reason}
        </p>
      )}

      <Link
        to={`/call-imports/${progress.call_import_id}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700"
      >
        Open import details
        <ExternalLink className="h-3 w-3" />
      </Link>
    </div>
  )
}

const STATUS_POLL_MS = 4000

export default function PlatformImportProgressDock() {
  const watches = usePlatformImportProgressStore((s) => s.watches)
  const panelOpen = usePlatformImportProgressStore((s) => s.panelOpen)
  const panelMinimized = usePlatformImportProgressStore((s) => s.panelMinimized)
  const setPanelOpen = usePlatformImportProgressStore((s) => s.setPanelOpen)
  const setPanelMinimized = usePlatformImportProgressStore((s) => s.setPanelMinimized)
  const unpin = usePlatformImportProgressStore((s) => s.unpin)
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const location = useLocation()
  const queryClient = useQueryClient()

  const progressQueries = useQueries({
    queries: watches.map((w) => ({
      queryKey: ['platform-import-progress', activeWorkspaceId, w.id],
      queryFn: () => apiClient.callImports.getPlatformImportProgress(w.id),
      refetchInterval: (query: { state: { data?: PlatformImportProgress } }) => {
        if (typeof document !== 'undefined' && document.hidden) return false
        if (location.pathname === `/call-imports/${w.id}`) return false
        const progress = query.state.data
        if (progress?.is_active !== true) return false
        return STATUS_POLL_MS
      },
      refetchOnWindowFocus: false,
      enabled: Boolean(w.id && activeWorkspaceId) && location.pathname !== `/call-imports/${w.id}`,
    })),
  })

  const progressSignature = progressQueries
    .map((query) => {
      const progress = query.data as PlatformImportProgress | undefined
      if (!progress) return ''
      return [
        progress.call_import_id,
        progress.status,
        progress.discovery_status,
        progress.recordings.total,
        progress.recordings.completed,
        progress.recordings.failed,
        progress.overall_percent,
      ].join(':')
    })
    .join('|')

  useEffect(() => {
    if (!activeWorkspaceId || !progressSignature) return
    const progresses = progressQueries
      .map((query) => query.data as PlatformImportProgress | undefined)
      .filter((progress): progress is PlatformImportProgress => Boolean(progress))
    queryClient.setQueriesData<CallImportListResponse>(
      { queryKey: ['call-imports', activeWorkspaceId] },
      (current) => {
        if (!current?.items?.length) return current
        let changed = false
        const items = current.items.map((item) => {
          const progress = progresses.find((row) => row.call_import_id === item.id)
          if (!progress) return item
          const status = progress.status as CallImport['status']
          if (
            item.status === status &&
            item.total_rows === progress.recordings.total &&
            item.completed_rows === progress.recordings.completed &&
            item.failed_rows === progress.recordings.failed &&
            (item.discovery_status ?? null) === (progress.discovery_status ?? null)
          ) {
            return item
          }
          changed = true
          return {
            ...item,
            status,
            total_rows: progress.recordings.total,
            completed_rows: progress.recordings.completed,
            failed_rows: progress.recordings.failed,
            discovery_status: progress.discovery_status,
            skip_counts: progress.skip_counts,
          }
        })
        return changed ? { ...current, items } : current
      },
    )
  }, [progressSignature, activeWorkspaceId, queryClient])

  const items = useMemo(() => {
    return watches.map((watch, i) => ({
      watch,
      progress: progressQueries[i]?.data as PlatformImportProgress | undefined,
      isLoading: progressQueries[i]?.isLoading,
      isError: progressQueries[i]?.isError,
      error: progressQueries[i]?.error,
    }))
  }, [watches, progressQueries])

  useEffect(() => {
    watches.forEach((watch, i) => {
      const err = progressQueries[i]?.error as { response?: { status?: number } } | undefined
      if (err?.response?.status === 404) {
        unpin(watch.id)
      }
    })
  }, [watches, progressQueries, unpin])

  const activeCount = items.filter((x) => x.progress?.is_active === true).length
  const headlinePercent =
    items.length === 1 && items[0].progress
      ? items[0].progress.overall_percent
      : items.reduce((sum, x) => sum + (x.progress?.overall_percent ?? 0), 0) /
        Math.max(items.filter((x) => x.progress).length, 1)

  if (watches.length === 0) return null

  const content = panelMinimized ? (
    <button
      type="button"
      onClick={() => {
        setPanelMinimized(false)
        setPanelOpen(true)
      }}
      className="fixed bottom-4 right-4 z-[10070] flex items-center gap-2 rounded-full border border-gray-200 bg-white px-4 py-2.5 shadow-lg hover:shadow-xl transition-shadow"
    >
      {activeCount > 0 ? (
        <Loader2 className="h-4 w-4 text-primary-600 animate-spin" />
      ) : (
        <CheckCircle2 className="h-4 w-4 text-green-600" />
      )}
        <span className="text-sm font-medium text-gray-900">
        Platform import{watches.length > 1 ? 's' : ''}
      </span>
      <span className="text-xs tabular-nums text-gray-500">{headlinePercent.toFixed(0)}%</span>
    </button>
  ) : (
    <div className="fixed bottom-4 right-4 z-[10070] w-[min(100vw-2rem,24rem)] rounded-xl border border-gray-200 bg-gray-50/95 shadow-2xl backdrop-blur-sm overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3 py-2.5 border-b border-gray-200 bg-white">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900">Platform imports</p>
          <p className="text-[11px] text-gray-500 truncate">
            {activeCount > 0 ? `${activeCount} running` : 'Finished'}
          </p>
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          <button
            type="button"
            onClick={() => setPanelOpen(!panelOpen)}
            className="p-1.5 rounded-md text-gray-500 hover:bg-gray-100"
            aria-label={panelOpen ? 'Collapse list' : 'Expand list'}
          >
            {panelOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={() => setPanelMinimized(true)}
            className="p-1.5 rounded-md text-gray-500 hover:bg-gray-100"
            aria-label="Minimize"
          >
            <Minus className="h-4 w-4" />
          </button>
        </div>
      </div>

      {panelOpen && (
        <div className="max-h-[min(70vh,28rem)] overflow-y-auto p-3 space-y-3 custom-scrollbar">
          {items.map(({ watch, progress, isLoading, isError }) => {
            const waitingOnPage =
              location.pathname === `/call-imports/${watch.id}` && !progress && !isError
            if ((isLoading && !progress) || waitingOnPage) {
              return (
                <div
                  key={watch.id}
                  className="rounded-lg border border-gray-200 bg-white p-4 flex items-center gap-2 text-sm text-gray-600"
                >
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading {watch.label}…
                </div>
              )
            }
            if (isError && !progress) {
              return (
                <div
                  key={watch.id}
                  className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800"
                >
                  Could not load {watch.label}.
                </div>
              )
            }
            if (!progress) return null
            return (
              <ImportProgressCard
                key={watch.id}
                progress={progress}
                label={watch.label}
                onDismiss={() => unpin(watch.id)}
              />
            )
          })}
        </div>
      )}
    </div>
  )

  if (typeof document === 'undefined') return null
  return createPortal(content, document.body)
}

export function usePinPlatformImport() {
  const pin = usePlatformImportProgressStore((s) => s.pin)
  return (id: string, label: string) => {
    pin(id, label)
  }
}
