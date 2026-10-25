import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ArrowLeft, Eye, Loader, RefreshCw, Trash2, Upload } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import type { KnowledgeDocument } from './knowledgeBaseTypes'
import UploadKnowledgeBaseModal from './components/UploadKnowledgeBaseModal'
import KnowledgeDocumentViewerModal from './components/KnowledgeDocumentViewerModal'
function statusClass(status: string) {
  if (status === 'ready') return 'text-green-700 bg-green-50'
  if (status === 'failed') return 'text-red-700 bg-red-50'
  if (status === 'processing') return 'text-amber-700 bg-amber-50'
  return 'text-gray-600 bg-gray-100'
}

function formatByteSize(bytes: number | null | undefined): string {
  if (bytes == null || bytes <= 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function KnowledgeBaseDetail() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showUpload, setShowUpload] = useState(false)
  const [viewDocumentId, setViewDocumentId] = useState<string | null>(null)
  const [viewDocumentName, setViewDocumentName] = useState<string | undefined>()

  const { data, isLoading } = useQuery({
    queryKey: ['knowledge-base', id],
    queryFn: () => apiClient.getKnowledgeBase(id!),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const docs = query.state.data?.documents as KnowledgeDocument[] | undefined
      if (docs?.some((d) => d.status === 'pending' || d.status === 'processing')) return 3000
      return false
    },
  })

  const deleteDocMutation = useMutation({
    mutationFn: (documentId: string) => apiClient.deleteKnowledgeDocument(id!, documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-base', id] })
      showToast('Document removed', 'success')
    },
  })

  const retryMutation = useMutation({
    mutationFn: (documentId: string) => apiClient.retryKnowledgeDocument(id!, documentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['knowledge-base', id] }),
  })

  const appendKnowledgeBaseEmbedding = useMemo(
    () =>
      data
        ? {
            provider: data.embedding_provider || 'openai',
            model: data.embedding_model || 'text-embedding-3-small',
            credential_id: data.embedding_credential_id ?? null,
          }
        : undefined,
    [data?.embedding_provider, data?.embedding_model, data?.embedding_credential_id],
  )

  if (!id) return null

  return (
    <div className="h-full flex flex-col bg-white">
      <ToastContainer />
      <div className="border-b border-gray-200 px-6 py-4 flex items-center gap-4">
        <Link to="/tools?tab=knowledge-bases" className="text-gray-500 hover:text-gray-800">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-semibold truncate">{data?.name ?? 'Knowledge base'}</h1>
          {data?.description && <p className="text-sm text-gray-600 truncate">{data.description}</p>}
        </div>
        <Button leftIcon={<Upload className="h-4 w-4" />} onClick={() => setShowUpload(true)}>
          Upload documents
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-8">
        {isLoading ? (
          <Loader className="h-5 w-5 animate-spin text-gray-400" />
        ) : (
          <>
            <section>
              <p className="text-sm text-gray-500 mb-4">
                Attach this base on <strong>Agents → Production Agent → Tools → Knowledge bases</strong> or{' '}
                <strong>Test Agent → Knowledge Bases</strong> for simulation RAG. Click a document to preview its
                contents.
              </p>
              {(data?.documents ?? []).length > 0 ? (
                <div className="bg-white shadow rounded-lg overflow-hidden border border-gray-200">
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Name
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Status
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Size
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Uploaded
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Error
                          </th>
                          <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Actions
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {(data?.documents ?? []).map((doc: KnowledgeDocument) => (
                          <tr key={doc.id} className="hover:bg-gray-50">
                            <td className="px-6 py-4 whitespace-nowrap max-w-xs">
                              <button
                                type="button"
                                className="text-sm font-medium text-primary-700 hover:underline flex items-center gap-2 truncate max-w-full"
                                onClick={() => {
                                  setViewDocumentId(doc.id)
                                  setViewDocumentName(doc.original_filename || undefined)
                                }}
                              >
                                <Eye className="h-4 w-4 shrink-0 opacity-60" />
                                <span className="truncate">{doc.original_filename || doc.id}</span>
                              </button>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              <span
                                className={`text-xs px-2 py-0.5 rounded-full ${statusClass(doc.status)}`}
                              >
                                {doc.status}
                              </span>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                              {formatByteSize(doc.byte_size)}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                              {doc.created_at
                                ? format(new Date(doc.created_at), 'MMM d, yyyy HH:mm')
                                : '—'}
                            </td>
                            <td className="px-6 py-4 text-sm text-red-600 max-w-xs">
                              {doc.error_text ? (
                                <span className="truncate block" title={doc.error_text}>
                                  {doc.error_text}
                                </span>
                              ) : (
                                <span className="text-gray-400">—</span>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-right">
                              <div className="flex items-center justify-end gap-1">
                                {doc.status === 'failed' && (
                                  <button
                                    type="button"
                                    className="p-1 text-gray-500 hover:text-primary-600"
                                    onClick={() => retryMutation.mutate(doc.id)}
                                    aria-label="Retry"
                                  >
                                    <RefreshCw className="h-4 w-4" />
                                  </button>
                                )}
                                <button
                                  type="button"
                                  className="p-1 text-gray-400 hover:text-red-600"
                                  onClick={() => deleteDocMutation.mutate(doc.id)}
                                  aria-label="Delete document"
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
                </div>
              ) : null}
              {!data?.documents?.length && (
                <div className="text-center py-12 space-y-3">
                  <p className="text-gray-500 text-sm">No documents yet.</p>
                  <Button variant="secondary" onClick={() => setShowUpload(true)}>
                    Upload documents
                  </Button>
                </div>
              )}
            </section>
          </>
        )}
      </div>

      <UploadKnowledgeBaseModal
        open={showUpload}
        onClose={() => setShowUpload(false)}
        appendToKnowledgeBaseId={id}
        appendToKnowledgeBaseName={data?.name}
        appendKnowledgeBaseEmbedding={appendKnowledgeBaseEmbedding}
      />

      <KnowledgeDocumentViewerModal
        open={Boolean(viewDocumentId)}
        onClose={() => {
          setViewDocumentId(null)
          setViewDocumentName(undefined)
        }}
        knowledgeBaseId={id}
        documentId={viewDocumentId}
        documentName={viewDocumentName}
      />
    </div>
  )
}
