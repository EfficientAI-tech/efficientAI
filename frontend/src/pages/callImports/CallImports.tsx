import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft,
  ChevronRight,
  FileAudio,
  FileSpreadsheet,
  Layers,
  Phone,
  Activity,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-react'
import { Tag as TagIcon } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorMessage } from '../../lib/apiErrors'
import { useToast } from '../../hooks/useToast'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { CallImport, CallImportStatus, CallImportTag } from '../../types/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import StatusBadge from '../../components/shared/StatusBadge'
import CallImportProgressBar from './components/CallImportProgressBar'
import UploadAudioModal from './components/UploadAudioModal'
import UploadCsvModal from './components/UploadCsvModal'
import ImportPlatformModal from './components/ImportPlatformModal'
import PlatformImportProgressDock, {
  usePinPlatformImport,
} from './components/PlatformImportProgressDock'
import { platformImportLabel } from './platformImportLabel'
import { itemsOf } from '../../lib/safeData'

const PAGE_SIZE = 20

const STATUS_OPTIONS: Array<{ label: string; value: '' | CallImportStatus }> = [
  { label: 'All statuses', value: '' },
  { label: 'Uploaded', value: 'uploaded' },
  { label: 'Mapped', value: 'mapped' },
  { label: 'Pending', value: 'pending' },
  { label: 'Processing', value: 'processing' },
  { label: 'Completed', value: 'completed' },
  { label: 'Partial', value: 'partial' },
  { label: 'Failed', value: 'failed' },
  { label: 'Deleting', value: 'deleting' },
]

type UploadTab = 'datasets' | 'audio' | 'platform'

export default function CallImports() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const pinPlatformImport = usePinPlatformImport()
  // Active workspace is part of every workspace-scoped queryKey so a
  // workspace switch produces a clean cache miss instead of leaking
  // rows from the previously-active workspace.
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<'' | CallImportStatus>('')
  const [datasetFilter, setDatasetFilter] = useState<string>('')
  const [tagFilter, setTagFilter] = useState<string[]>([])
  const [activeTab, setActiveTab] = useState<UploadTab>('datasets')
  const [showUpload, setShowUpload] = useState(false)
  const [showAudioUpload, setShowAudioUpload] = useState(false)
  const [showPlatformImport, setShowPlatformImport] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<CallImport | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const { data: datasets = [] } = useQuery({
    queryKey: ['call-import-datasets', activeWorkspaceId],
    queryFn: () => apiClient.listCallImportDatasets(),
  })

  const { data: allTags = [] } = useQuery({
    queryKey: ['call-import-tags', activeWorkspaceId],
    queryFn: () => apiClient.listCallImportTags(),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteCallImport(id),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      setPendingDelete(null)
      setDeleteError(null)
      if (result.status === 'accepted') {
        showToast(
          'Deletion started — large imports may take a minute.',
          'success',
        )
      }
    },
    onError: (err: unknown) => {
      const message = getApiErrorMessage(err, 'Failed to delete import.')
      setDeleteError(message)
      showToast(message, 'error')
    },
  })

  const queryParams = useMemo(
    () => ({
      page,
      page_size: PAGE_SIZE,
      ...(statusFilter ? { status: statusFilter } : {}),
      ...(datasetFilter ? { dataset: datasetFilter } : {}),
      ...(tagFilter.length > 0 ? { tag_id: tagFilter } : {}),
      source_format:
        activeTab === 'audio'
          ? 'audio'
          : activeTab === 'platform'
            ? 'platform'
            : '__non_audio__',
    }),
    [page, statusFilter, datasetFilter, tagFilter, activeTab],
  )

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['call-imports', activeWorkspaceId, queryParams],
    queryFn: () => apiClient.listCallImports(queryParams),
    refetchInterval: (query) => {
      const items = itemsOf<CallImport>(query.state.data)
      const hasActive = items.some(
        (i: CallImport) => i.status === 'pending' || i.status === 'processing',
      )
      const hasDeleting = items.some(
        (i: CallImport) => i.status === 'deleting',
      )
      if (hasDeleting) return 3000
      return hasActive ? 5000 : false
    },
  })

  const items = itemsOf<CallImport>(data)
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="space-y-6">
      <ToastContainer />
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Imports</h1>
          {activeTab !== 'platform' && (
            <p className="mt-2 text-sm text-gray-600">
              {activeTab === 'audio'
                ? 'Upload recordings directly for diarisation and evaluation.'
                : 'Upload CSV or Excel datasets, map columns, and import call recordings.'}
            </p>
          )}
        </div>
        <div className="flex gap-3">
          {activeTab === 'datasets' && (
            <>
              <Link to="/call-imports/schemas">
                <Button
                  variant="ghost"
                  leftIcon={<Layers className="h-5 w-5" />}
                >
                  Manage Schemas
                </Button>
              </Link>
              <Link to="/call-imports/tags">
                <Button
                  variant="ghost"
                  leftIcon={<TagIcon className="h-5 w-5" />}
                >
                  Manage Tags
                </Button>
              </Link>
            </>
          )}
          <Button
            variant="primary"
            onClick={() => {
              if (activeTab === 'audio') setShowAudioUpload(true)
              else if (activeTab === 'platform') setShowPlatformImport(true)
              else setShowUpload(true)
            }}
            leftIcon={<Upload className="h-5 w-5" />}
          >
            {activeTab === 'audio'
              ? 'Upload recording'
              : activeTab === 'platform'
                ? 'New platform import'
                : 'Upload CSV'}
          </Button>
          <Button
            variant="secondary"
            onClick={() => refetch()}
            isLoading={isFetching && !isLoading}
            leftIcon={!(isFetching && !isLoading) ? <RefreshCw className="h-5 w-5" /> : undefined}
          >
            Refresh
          </Button>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg p-1 inline-flex gap-1">
        <button
          type="button"
          onClick={() => {
            setActiveTab('datasets')
            setPage(1)
          }}
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'datasets'
              ? 'bg-primary-50 text-primary-700'
              : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
          }`}
        >
          <FileSpreadsheet className="h-4 w-4" />
          CSV / Dataset Uploads
        </button>
        <button
          type="button"
          onClick={() => {
            setActiveTab('audio')
            setPage(1)
          }}
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'audio'
              ? 'bg-primary-50 text-primary-700'
              : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
          }`}
        >
          <FileAudio className="h-4 w-4" />
          Manual Upload
        </button>
        <button
          type="button"
          onClick={() => {
            setActiveTab('platform')
            setPage(1)
          }}
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'platform'
              ? 'bg-primary-50 text-primary-700'
              : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
          }`}
        >
          <Phone className="h-4 w-4" />
          Platforms
        </button>
      </div>

      {/*
        High-level dataset segregation lives at the top of the page so users can
        scope all filtering/searching that follows to a specific dataset. We
        intentionally render this above the main card to make it visually
        distinct from the in-card status/tag filters.
      */}
      <div className="bg-white shadow rounded-lg p-4 flex items-center gap-3 flex-wrap">
        <label htmlFor="dataset-filter" className="text-sm font-medium text-gray-700">
          Dataset:
        </label>
        <select
          id="dataset-filter"
          value={datasetFilter}
          onChange={(e) => {
            setDatasetFilter(e.target.value)
            setPage(1)
          }}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-transparent min-w-[12rem]"
        >
          <option value="">All datasets</option>
          {datasets.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        {datasetFilter && (
          <span className="text-xs text-gray-500">
            Showing imports tagged with dataset “{datasetFilter}”.
          </span>
        )}
      </div>

      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center justify-between mb-4 gap-4 flex-wrap">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <label htmlFor="status-filter" className="text-sm text-gray-600">
                Status:
              </label>
              <select
                id="status-filter"
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value as '' | CallImportStatus)
                  setPage(1)
                }}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              >
                {STATUS_OPTIONS.map((opt) => (
                  <option key={opt.value || 'all'} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            {allTags.length > 0 && (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm text-gray-600">Tags:</span>
                {allTags.map((tag: CallImportTag) => {
                  const active = tagFilter.includes(tag.id)
                  return (
                    <button
                      key={tag.id}
                      type="button"
                      onClick={() => {
                        setTagFilter((prev) =>
                          prev.includes(tag.id)
                            ? prev.filter((t) => t !== tag.id)
                            : [...prev, tag.id],
                        )
                        setPage(1)
                      }}
                      className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                        active
                          ? 'bg-primary-600 border-primary-600 text-white'
                          : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
                      }`}
                      style={
                        !active && tag.color
                          ? { borderColor: tag.color, color: tag.color }
                          : undefined
                      }
                    >
                      {tag.name}
                    </button>
                  )
                })}
                {tagFilter.length > 0 && (
                  <button
                    type="button"
                    onClick={() => {
                      setTagFilter([])
                      setPage(1)
                    }}
                    className="text-xs text-gray-500 hover:text-gray-700 underline"
                  >
                    Clear
                  </button>
                )}
              </div>
            )}
          </div>
          <p className="text-sm text-gray-500">
            {total}{' '}
            {activeTab === 'audio'
              ? `manual upload${total === 1 ? '' : 's'}`
              : activeTab === 'platform'
                ? `platform import${total === 1 ? '' : 's'}`
                : `dataset import${total === 1 ? '' : 's'}`}
          </p>
        </div>

        {isLoading ? (
          <div className="text-center py-12 text-gray-500">
            <RefreshCw className="h-8 w-8 mx-auto mb-2 animate-spin" />
            <p>Loading imports...</p>
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-12">
            <Phone className="h-12 w-12 mx-auto mb-3 text-gray-300" />
            <p className="text-gray-500 mb-3">
              {statusFilter
                ? 'No imports match this filter.'
                : activeTab === 'audio'
                  ? 'No manual uploads yet.'
                  : activeTab === 'platform'
                    ? 'No platform imports yet.'
                    : 'No dataset uploads yet.'}
            </p>
            {!statusFilter && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  if (activeTab === 'audio') setShowAudioUpload(true)
                  else if (activeTab === 'platform') setShowPlatformImport(true)
                  else setShowUpload(true)
                }}
                leftIcon={<Upload className="h-4 w-4" />}
              >
                {activeTab === 'audio'
                  ? 'Upload your first recording'
                  : activeTab === 'platform'
                    ? 'Import from a platform'
                    : 'Upload your first CSV'}
              </Button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Filename
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Provider
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Dataset / Tags
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-64">
                    Progress
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {items.map((item: CallImport) => {
                  const isDeleting = item.status === 'deleting'
                  return (
                  <tr
                    key={item.id}
                    className={`hover:bg-gray-50 ${isDeleting ? 'opacity-60' : 'cursor-pointer'}`}
                    onClick={() => {
                      if (isDeleting) return
                      navigate(`/call-imports/${item.id}`)
                    }}
                  >
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm font-medium text-gray-900 truncate max-w-xs">
                        {item.source_format === 'platform'
                          ? platformImportLabel(item)
                          : item.original_filename || '(unnamed)'}
                      </div>
                      {item.source_format === 'platform' &&
                        item.window_start &&
                        item.window_end && (
                          <div className="text-xs text-gray-500 mt-0.5">
                            {new Date(item.window_start).toLocaleDateString()} –{' '}
                            {new Date(item.window_end).toLocaleDateString()}
                          </div>
                        )}
                      <div className="text-xs text-gray-400 font-mono mt-0.5">
                        {item.id.slice(0, 8)}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700 capitalize">
                      {item.source_format === 'audio' ? (
                        <span className="inline-flex items-center gap-1 normal-case text-gray-700">
                          <FileAudio className="h-3.5 w-3.5" />
                          Manual Upload
                        </span>
                      ) : item.source_format === 'platform' ? (
                        <span className="inline-flex flex-col normal-case">
                          <span>{item.provider || 'platform'}</span>
                          {item.discovery_status === 'failed' ? (
                            <span className="text-xs text-red-600 font-normal">
                              Discovery failed
                            </span>
                          ) : item.discovery_status &&
                            !['completed', 'capped', 'partial'].includes(
                              item.discovery_status,
                            ) &&
                            (item.status === 'processing' ||
                              item.status === 'pending') ? (
                            <span className="text-xs text-amber-600 font-normal">
                              Discovering…
                            </span>
                          ) : null}
                        </span>
                      ) : (
                        item.provider || (
                          <span className="text-gray-400 italic normal-case">
                            —
                          </span>
                        )
                      )}
                    </td>
                    <td className="px-6 py-4 align-top">
                      <div className="flex flex-col gap-1">
                        {item.dataset ? (
                          <span className="inline-flex items-center text-xs font-medium text-gray-800 bg-gray-100 rounded px-2 py-0.5 self-start">
                            {item.dataset}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400 italic">
                            no dataset
                          </span>
                        )}
                        {item.tags.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {item.tags.map((tag) => (
                              <span
                                key={tag.id}
                                className="inline-flex items-center text-[10px] uppercase tracking-wide rounded-full px-2 py-0.5 border"
                                style={{
                                  borderColor: tag.color || '#d1d5db',
                                  color: tag.color || '#4b5563',
                                }}
                              >
                                {tag.name}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <CallImportProgressBar
                        total={item.total_rows}
                        completed={item.completed_rows}
                        failed={item.failed_rows}
                        deleting={isDeleting}
                      />
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {item.latest_evaluation_status ? (
                        <span className="inline-flex flex-col gap-0.5">
                          <span className="text-[10px] text-gray-500">Latest eval</span>
                          <StatusBadge
                            status={item.latest_evaluation_status}
                            size="sm"
                          />
                        </span>
                      ) : (
                        <StatusBadge status={item.status} />
                      )}
                    </td>
                    <td
                      className="px-6 py-4 whitespace-nowrap text-right text-sm"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex justify-end items-center gap-3">
                        <Link
                          to={`/call-imports/${item.id}`}
                          className={`font-medium ${isDeleting ? 'pointer-events-none text-gray-400' : 'text-primary-600 hover:text-primary-700'}`}
                          aria-disabled={isDeleting}
                          tabIndex={isDeleting ? -1 : undefined}
                        >
                          View
                        </Link>
                        {item.source_format === 'platform' &&
                          !isDeleting &&
                          (item.status === 'processing' || item.status === 'pending') && (
                          <button
                            type="button"
                            className="text-gray-500 hover:text-primary-600 transition-colors"
                            title="Track live import progress"
                            onClick={() => {
                              pinPlatformImport(item.id, platformImportLabel(item))
                            }}
                          >
                            <Activity className="h-4 w-4" />
                          </button>
                        )}
                        <button
                          type="button"
                          aria-label={`Delete ${item.original_filename || 'import'}`}
                          title="Delete import"
                          className="text-gray-400 hover:text-red-600 transition-colors disabled:opacity-40"
                          onClick={() => {
                            setDeleteError(null)
                            setPendingDelete(item)
                          }}
                          disabled={
                            isDeleting ||
                            (deleteMutation.isPending && pendingDelete?.id === item.id)
                          }
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

            {totalPages > 1 && (
              <div className="px-6 py-3 bg-gray-50 border-t border-gray-200 flex items-center justify-between">
                <p className="text-sm text-gray-600">
                  Page {page} of {totalPages}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    leftIcon={<ChevronLeft className="h-4 w-4" />}
                  >
                    Prev
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                    rightIcon={<ChevronRight className="h-4 w-4" />}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <UploadCsvModal open={showUpload} onClose={() => setShowUpload(false)} />
      <ImportPlatformModal
        open={showPlatformImport}
        onClose={() => setShowPlatformImport(false)}
        onImportStarted={() => {
          queryClient.invalidateQueries({ queryKey: ['call-imports'] })
        }}
      />
      <UploadAudioModal
        open={showAudioUpload}
        onClose={() => setShowAudioUpload(false)}
      />

      <ConfirmModal
        isOpen={pendingDelete !== null}
        title="Delete call import?"
        description={(() => {
          if (!pendingDelete) return ''
          const name = pendingDelete.original_filename || '(unnamed)'
          const inFlight =
            pendingDelete.status === 'pending' ||
            pendingDelete.status === 'processing' ||
            pendingDelete.status === 'deleting'
          const lines = [
            `“${name}” will be permanently deleted, along with all of its recordings.`,
            inFlight
              ? 'This batch is still processing — pending tasks will be revoked before deletion.'
              : '',
            'This cannot be undone.',
            deleteError ? `Error: ${deleteError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        confirmPhrase="confirm"
        variant="danger"
        isLoading={deleteMutation.isPending}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id)
        }}
        onCancel={() => {
          if (deleteMutation.isPending) return
          setPendingDelete(null)
          setDeleteError(null)
        }}
      />
      <PlatformImportProgressDock />
    </div>
  )
}
