import { Link } from 'react-router-dom'
import { BookOpen } from 'lucide-react'
import type { KnowledgeBaseSummary } from '../../knowledgeBases/knowledgeBaseTypes'

interface AgentKnowledgeBasesPanelProps {
  mode: 'view' | 'edit'
  attachedIds: string[]
  knowledgeBases: KnowledgeBaseSummary[]
  onChange?: (ids: string[]) => void
  compact?: boolean
  /** Which side these bases serve; each side has its own list. */
  side?: 'production' | 'test'
}

const SIDE_COPY = {
  production: {
    title: 'Production agent knowledge bases',
    compact: 'Searched by the agent under test when it answers.',
    full: 'Document libraries the production agent searches during chat simulation, telephony, and eval runs.',
  },
  test: {
    title: 'Test agent knowledge bases',
    compact: 'Facts the simulated customer can look up (order details, account data).',
    full: 'Document libraries the simulated customer searches during chat simulation and the voice playground. Independent of the production agent.',
  },
}

export default function AgentKnowledgeBasesPanel({
  mode,
  attachedIds,
  knowledgeBases,
  onChange,
  compact = false,
  side = 'production',
}: AgentKnowledgeBasesPanelProps) {
  const attached = knowledgeBases.filter((kb) => attachedIds.includes(kb.id))
  const copy = SIDE_COPY[side]

  return (
    <div className={compact ? 'space-y-2' : 'space-y-4'}>
      <div>
        <h3 className={compact ? 'text-sm font-semibold text-gray-900' : 'text-base font-semibold text-gray-900'}>
          {copy.title}
        </h3>
        <p className={`text-gray-500 mt-0.5 ${compact ? 'text-xs' : 'text-sm'}`}>
          {compact ? copy.compact : copy.full}
        </p>
      </div>

      {knowledgeBases.length === 0 ? (
        <p className="text-sm text-gray-500">
          No knowledge bases in this workspace yet.{' '}
          <Link to="/tools?tab=knowledge-bases" className="text-primary-700 hover:underline">
            Create one
          </Link>
          .
        </p>
      ) : mode === 'edit' ? (
        <ul
          className={`space-y-2 overflow-y-auto border border-gray-200 rounded-lg p-3 bg-white ${
            compact ? 'max-h-40' : 'max-h-64'
          }`}
        >
          {knowledgeBases.map((kb) => {
            const checked = attachedIds.includes(kb.id)
            return (
              <li key={kb.id}>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      if (!onChange) return
                      const next = checked
                        ? attachedIds.filter((id) => id !== kb.id)
                        : [...attachedIds, kb.id]
                      onChange(next)
                    }}
                  />
                  <span>{kb.name}</span>
                  {typeof kb.ready_document_count === 'number' && (
                    <span className="text-xs text-gray-400">({kb.ready_document_count} ready)</span>
                  )}
                </label>
              </li>
            )
          })}
        </ul>
      ) : attached.length === 0 ? (
        <p className="text-sm text-gray-500">
          No knowledge bases attached. Use Edit to link bases with indexed documents.
        </p>
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
                    Documents
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Embedding
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {attached.map((kb) => (
                  <tr key={kb.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Link
                        to={`/knowledge-bases/${kb.id}`}
                        className="text-sm font-medium text-primary-700 hover:underline inline-flex items-center gap-2"
                      >
                        <BookOpen className="h-4 w-4 opacity-60" />
                        {kb.name}
                      </Link>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                      {kb.ready_document_count}/{kb.document_count} ready
                      {kb.failed_document_count > 0 ? (
                        <span className="text-red-600"> · {kb.failed_document_count} failed</span>
                      ) : null}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600 font-mono max-w-xs truncate">
                      {(kb.embedding_provider || 'openai')}/{kb.embedding_model || 'text-embedding-3-small'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
