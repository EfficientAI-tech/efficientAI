import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft,
  ChevronRight,
  Layers,
  Phone,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-react'
import { Tag as TagIcon } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { CallImport, CallImportStatus, CallImportTag } from '../../types/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import StatusBadge from '../../components/shared/StatusBadge'
import CallImportProgressBar from './components/CallImportProgressBar'
import UploadCsvModal from './components/UploadCsvModal'

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
]

export default function CallImports() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // Active workspace is part of every workspace-scoped queryKey so a
  // workspace switch produces a clean cache miss instead of leaking
  // rows from the previously-active workspace.
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<'' | CallImportStatus>('')
  const [datasetFilter, setDatasetFilter] = useState<string>('')
  const [tagFilter, setTagFilter] = useState<string[]>([])
  const [showUpload, setShowUpload] = useState(false)
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      setPendingDelete(null)
      setDeleteError(null)
    },
    onError: (err: any) => {
      setDeleteError(
        err?.response?.data?.detail || err?.message || 'Failed to delete import.',
      )
    },
  })

  const queryParams = useMemo(
    () => ({
      page,
      page_size: PAGE_SIZE,
      ...(statusFilter ? { status: statusFilter } : {}),
      ...(datasetFilter ? { dataset: datasetFilter } : {}),
      ...(tagFilter.length > 0 ? { tag_id: tagFilter } : {}),
    }),
    [page, statusFilter, datasetFilter, tagFilter],
  )

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['call-imports', activeWorkspaceId, queryParams],
    queryFn: () => apiClient.listCallImports(queryParams),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      const hasActive = items.some(
        (i: CallImport) => i.status === 'pending' || i.status === 'processing',
      )
      return hasActive ? 5000 : false
    },
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Call Imports</h1>
          <p className="mt-2 text-sm text-gray-600">
            Pick a reusable Input Parameter schema, map its parameters to the
            columns of your CSV / Excel sheet, and we'll fetch each recording
            from the selected telephony provider into S3.
          </p>
        </div>
        <div className="flex gap-3">
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
          <Button
            variant="primary"
            onClick={() => setShowUpload(true)}
            leftIcon={<Upload className="h-5 w-5" />}
          >
            Upload CSV
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
            {total} import{total === 1 ? '' : 's'}
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
              {statusFilter ? 'No imports match this filter.' : 'No imports yet.'}
            </p>
            {!statusFilter && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowUpload(true)}
                leftIcon={<Upload className="h-4 w-4" />}
              >
                Upload your first CSV
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
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Created
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {items.map((item: CallImport) => (
                  <tr
                    key={item.id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() => navigate(`/call-imports/${item.id}`)}
                  >
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm font-medium text-gray-900 truncate max-w-xs">
                        {item.original_filename || '(unnamed)'}
                      </div>
                      <div className="text-xs text-gray-400 font-mono mt-0.5">
                        {item.id.slice(0, 8)}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700 capitalize">
                      {item.provider || (
                        <span className="text-gray-400 italic normal-case">
                          —
                        </span>
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
                      />
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <StatusBadge status={item.status} />
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {new Date(item.created_at).toLocaleString()}
                    </td>
                    <td
                      className="px-6 py-4 whitespace-nowrap text-right text-sm"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex justify-end items-center gap-3">
                        <Link
                          to={`/call-imports/${item.id}`}
                          className="text-primary-600 hover:text-primary-700 font-medium"
                        >
                          View
                        </Link>
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
                            deleteMutation.isPending && pendingDelete?.id === item.id
                          }
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
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

      <ConfirmModal
        isOpen={pendingDelete !== null}
        title="Delete call import?"
        description={(() => {
          if (!pendingDelete) return ''
          const name = pendingDelete.original_filename || '(unnamed)'
          const total = pendingDelete.total_rows
          const completed = pendingDelete.completed_rows
          const inFlight =
            pendingDelete.status === 'pending' || pendingDelete.status === 'processing'
          const lines = [
            `“${name}” will be permanently deleted, along with all ${total} row record${total === 1 ? '' : 's'} and ${completed} stored recording${completed === 1 ? '' : 's'} in S3.`,
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
    </div>
  )
}
