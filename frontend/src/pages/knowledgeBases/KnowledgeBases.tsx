import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Loader, Trash2, Upload } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import type { KnowledgeBaseSummary } from './knowledgeBaseTypes'
import UploadKnowledgeBaseModal from './components/UploadKnowledgeBaseModal'

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  openrouter: 'OpenRouter',
  anthropic: 'Anthropic',
  google: 'Google',
  fireworks: 'Fireworks AI',
  cohere: 'Cohere',
  mistral: 'Mistral',
  together: 'Together',
  azure: 'Azure',
  aws: 'AWS',
}

function embeddingLabel(kb: KnowledgeBaseSummary): string {
  const provider = kb.embedding_provider || 'openai'
  const model = kb.embedding_model || 'text-embedding-3-small'
  const providerName = PROVIDER_LABELS[provider] ?? provider
  return `${providerName} / ${model}`
}

/** ``embedded``: rendered as a tab of the Tools page, which supplies the page title. */
export default function KnowledgeBases({ embedded = false }: { embedded?: boolean }) {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showUpload, setShowUpload] = useState(false)

  const { data: bases = [], isLoading } = useQuery({
    queryKey: ['knowledge-bases'],
    queryFn: () => apiClient.listKnowledgeBases(),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteKnowledgeBase(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] })
      showToast('Knowledge base deleted', 'success')
    },
    onError: (err: Error) => showToast(err.message || 'Delete failed', 'error'),
  })

  return (
    <div className="h-full flex flex-col bg-white">
      <ToastContainer />
      <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div>
          {!embedded ? (
            <div className="flex items-center gap-2">
              <BookOpen className="h-5 w-5 text-primary-600" />
              <h1 className="text-xl font-semibold text-gray-900">Knowledge Bases</h1>
            </div>
          ) : null}
          <p className={`text-sm text-gray-500 ${embedded ? '' : 'mt-1'}`}>
            Document libraries the production and test agents search during simulations — attach production bases
            under Production Agent → Tools → Knowledge bases, and test bases on each agent’s Test Agent tab.
          </p>
        </div>
        <Button onClick={() => setShowUpload(true)} leftIcon={<Upload className="h-4 w-4" />}>
          Upload
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex items-center gap-2 text-gray-500">
            <Loader className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : bases.length === 0 ? (
          <div className="max-w-lg text-center mx-auto py-12 space-y-4">
            <p className="text-gray-600">No knowledge bases yet.</p>
            <Button onClick={() => setShowUpload(true)} leftIcon={<Upload className="h-4 w-4" />}>
              Upload your first documents
            </Button>
          </div>
        ) : (
          <div className="bg-white shadow rounded-lg overflow-hidden border border-gray-200">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Name
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Description
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Documents
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Agents
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Embedding
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {bases.map((kb: KnowledgeBaseSummary) => (
                    <tr key={kb.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <Link
                          to={`/knowledge-bases/${kb.id}`}
                          className="text-sm font-medium text-primary-700 hover:underline"
                        >
                          {kb.name}
                        </Link>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-600 max-w-xs">
                        <span className="line-clamp-2">{kb.description || '—'}</span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                        {kb.ready_document_count}/{kb.document_count} ready
                        {kb.failed_document_count > 0 ? (
                          <span className="text-red-600"> · {kb.failed_document_count} failed</span>
                        ) : null}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                        {kb.linked_agent_count > 0 ? kb.linked_agent_count : '—'}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-600 font-mono max-w-xs">
                        <span className="truncate block" title={embeddingLabel(kb)}>
                          {embeddingLabel(kb)}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <button
                          type="button"
                          className="text-gray-400 hover:text-red-600 p-1"
                          aria-label="Delete"
                          onClick={() => {
                            if (window.confirm(`Delete "${kb.name}"?`)) deleteMutation.mutate(kb.id)
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <UploadKnowledgeBaseModal open={showUpload} onClose={() => setShowUpload(false)} />
    </div>
  )
}
