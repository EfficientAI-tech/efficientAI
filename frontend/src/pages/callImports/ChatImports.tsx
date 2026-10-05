import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft,
  ChevronRight,
  FileSpreadsheet,
  Layers,
  MessageSquare,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-react'
import { Tag as TagIcon } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorMessage } from '../../lib/apiErrors'
import { useToast } from '../../hooks/useToast'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { CallImport, CallImportStatus } from '../../types/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import StatusBadge from '../../components/shared/StatusBadge'
import CallImportProgressBar from './components/CallImportProgressBar'
import UploadChatCsvModal from './components/UploadChatCsvModal'
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

export default function ChatImports() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const initialSchemaId = searchParams.get('schema_id')

  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<'' | CallImportStatus>('')
  const [datasetFilter, setDatasetFilter] = useState<string>('')
  const [tagFilter] = useState<string[]>([])
  const [showUpload, setShowUpload] = useState(Boolean(searchParams.get('upload')))
  const [pendingDelete, setPendingDelete] = useState<CallImport | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const { data: datasets = [] } = useQuery({
    queryKey: ['call-import-datasets', activeWorkspaceId],
    queryFn: () => apiClient.listCallImportDatasets(),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteCallImport(id),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['chat-imports'] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      setPendingDelete(null)
      setDeleteError(null)
      if (result.status === 'accepted') {
        showToast('Deletion started — large imports may take a minute.', 'success')
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
      content_modality: 'chat',
      source_format: '__non_audio__',
      ...(statusFilter ? { status: statusFilter } : {}),
      ...(datasetFilter ? { dataset: datasetFilter } : {}),
      ...(tagFilter.length > 0 ? { tag_id: tagFilter } : {}),
    }),
    [page, statusFilter, datasetFilter, tagFilter],
  )

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['chat-imports', activeWorkspaceId, queryParams],
    queryFn: () => apiClient.listCallImports(queryParams),
    refetchInterval: (query) => {
      const items = itemsOf<CallImport>(query.state.data)
      const hasActive = items.some(
        (i) => i.status === 'pending' || i.status === 'processing',
      )
      const hasDeleting = items.some((i) => i.status === 'deleting')
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
      <div className="flex justify-between items-center gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-2">
            <MessageSquare className="h-8 w-8 text-primary-600" />
            Chat imports
          </h1>
          <p className="mt-2 text-sm text-gray-600 max-w-2xl">
            Post-prod chat transcript batches for evaluator runs. Uses the same map and import
            pipeline as call imports, tagged with <code className="text-xs">content_modality=chat</code>.
          </p>
          <p className="mt-1 text-xs text-gray-500">
            Voice call imports remain on{' '}
            <Link to="/call-imports" className="text-primary-600 hover:underline">
              Call imports
            </Link>
            .
          </p>
        </div>
        <div className="flex gap-3 flex-wrap">
          <Link to="/call-imports/schemas">
            <Button variant="ghost" leftIcon={<Layers className="h-5 w-5" />}>
              Schemas
            </Button>
          </Link>
          <Link to="/call-imports/tags">
            <Button variant="ghost" leftIcon={<TagIcon className="h-5 w-5" />}>
              Tags
            </Button>
          </Link>
          <Button
            variant="primary"
            onClick={() => setShowUpload(true)}
            leftIcon={<Upload className="h-5 w-5" />}
          >
            Upload transcripts
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

      <div className="bg-white shadow rounded-lg p-4 flex items-center gap-3 flex-wrap">
        <label htmlFor="chat-dataset-filter" className="text-sm font-medium text-gray-700">
          Dataset:
        </label>
        <select
          id="chat-dataset-filter"
          value={datasetFilter}
          onChange={(e) => {
            setDatasetFilter(e.target.value)
            setPage(1)
          }}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-md min-w-[12rem]"
        >
          <option value="">All datasets</option>
          {datasets.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </div>

      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center justify-between mb-4 gap-4 flex-wrap">
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value as '' | CallImportStatus)
              setPage(1)
            }}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded-md"
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value || 'all'} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <p className="text-sm text-gray-500">{total} chat import{total === 1 ? '' : 's'}</p>
        </div>

        {isLoading ? (
          <div className="text-center py-12 text-gray-500">
            <RefreshCw className="h-8 w-8 mx-auto mb-2 animate-spin" />
            Loading…
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-12">
            <FileSpreadsheet className="h-12 w-12 mx-auto mb-3 text-gray-300" />
            <p className="text-gray-500 mb-3">No chat transcript imports yet.</p>
            <Button variant="ghost" size="sm" onClick={() => setShowUpload(true)} leftIcon={<Upload className="h-4 w-4" />}>
              Upload transcripts
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">File</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Dataset</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase w-64">Progress</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {items.map((item) => {
                  const isDeleting = item.status === 'deleting'
                  return (
                    <tr
                      key={item.id}
                      className={`hover:bg-gray-50 ${isDeleting ? 'opacity-60' : 'cursor-pointer'}`}
                      onClick={() => {
                        if (!isDeleting) navigate(`/call-imports/${item.id}`)
                      }}
                    >
                      <td className="px-6 py-4">
                        <div className="text-sm font-medium text-gray-900 truncate max-w-xs">
                          {item.original_filename || '(unnamed)'}
                        </div>
                        <div className="text-xs text-gray-400 font-mono">{item.id.slice(0, 8)}</div>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-700">{item.dataset || '—'}</td>
                      <td className="px-6 py-4">
                        <CallImportProgressBar
                          total={item.total_rows}
                          completed={item.completed_rows}
                          failed={item.failed_rows}
                          deleting={item.status === 'deleting'}
                        />
                      </td>
                      <td className="px-6 py-4">
                        <StatusBadge status={item.status} />
                      </td>
                      <td className="px-6 py-4 text-right">
                        <button
                          type="button"
                          className="text-gray-400 hover:text-red-600 p-1"
                          onClick={(e) => {
                            e.stopPropagation()
                            setPendingDelete(item)
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-6 pt-4 border-t border-gray-100">
            <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} leftIcon={<ChevronLeft className="h-4 w-4" />}>
              Previous
            </Button>
            <span className="text-sm text-gray-500">Page {page} of {totalPages}</span>
            <Button variant="ghost" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)} leftIcon={<ChevronRight className="h-4 w-4" />}>
              Next
            </Button>
          </div>
        )}
      </div>

      <UploadChatCsvModal
        open={showUpload}
        onClose={() => setShowUpload(false)}
        initialSchemaId={initialSchemaId}
      />

      <ConfirmModal
        isOpen={!!pendingDelete}
        title="Delete chat import?"
        description={
          deleteError ||
          `Remove batch "${pendingDelete?.original_filename || pendingDelete?.id}"? This cannot be undone.`
        }
        confirmLabel="Delete"
        variant="danger"
        isLoading={deleteMutation.isPending}
        onConfirm={() => pendingDelete && deleteMutation.mutate(pendingDelete.id)}
        onCancel={() => {
          setPendingDelete(null)
          setDeleteError(null)
        }}
      />
    </div>
  )
}
