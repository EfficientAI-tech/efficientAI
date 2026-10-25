import { useQuery } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { FileText, Loader, X } from 'lucide-react'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'
import type { KnowledgeDocumentView } from '../knowledgeBaseTypes'

interface KnowledgeDocumentViewerModalProps {
  open: boolean
  onClose: () => void
  knowledgeBaseId: string
  documentId: string | null
  documentName?: string
}

export default function KnowledgeDocumentViewerModal({
  open,
  onClose,
  knowledgeBaseId,
  documentId,
  documentName,
}: KnowledgeDocumentViewerModalProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['knowledge-document-view', knowledgeBaseId, documentId],
    queryFn: () => apiClient.getKnowledgeDocumentView(knowledgeBaseId, documentId!),
    enabled: open && Boolean(documentId),
  })

  if (!open || !documentId || typeof document === 'undefined') return null

  const view = data as KnowledgeDocumentView | undefined
  const downloadUrl = apiClient.knowledgeDocumentDownloadUrl(knowledgeBaseId, documentId)

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-gray-900">
              <FileText className="h-5 w-5 shrink-0 text-primary-600" />
              <h2 className="text-lg font-semibold truncate">
                {view?.original_filename || documentName || 'Document'}
              </h2>
            </div>
            {view?.knowledge_base_name && (
              <p className="text-sm text-gray-500 mt-1">
                Knowledge base: <span className="font-medium">{view.knowledge_base_name}</span>
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {isLoading && (
            <div className="flex items-center gap-2 text-gray-500">
              <Loader className="h-4 w-4 animate-spin" /> Loading document…
            </div>
          )}
          {error && (
            <p className="text-sm text-red-600">Could not load this document. Try download instead.</p>
          )}
          {view?.view_mode === 'text' || view?.view_mode === 'docx' ? (
            <pre className="text-sm whitespace-pre-wrap font-mono text-gray-800 bg-gray-50 border border-gray-200 rounded-lg p-4">
              {view.text_content || '(empty file)'}
            </pre>
          ) : null}
          {view?.view_mode === 'pdf' && view.pages && view.pages.length > 0 ? (
            <div className="space-y-6">
              {view.pages.map((page, idx) => (
                <section key={page.page ?? idx}>
                  {page.page != null && (
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                      Page {page.page}
                    </h3>
                  )}
                  <pre className="text-sm whitespace-pre-wrap text-gray-800 bg-gray-50 border border-gray-200 rounded-lg p-4">
                    {page.text || '(no extractable text on this page)'}
                  </pre>
                </section>
              ))}
            </div>
          ) : null}
          {view?.view_mode === 'pdf' && (!view.pages || view.pages.length === 0) && (
            <p className="text-sm text-gray-600">
              No text could be extracted from this PDF. Open the original file to view it.
            </p>
          )}
        </div>

        <div className="border-t border-gray-200 px-5 py-3 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <a href={downloadUrl} target="_blank" rel="noopener noreferrer">
            <Button type="button">Open original file</Button>
          </a>
        </div>
      </div>
    </div>,
    document.body,
  )
}
