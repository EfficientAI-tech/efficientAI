import { useState } from 'react'
import { BookOpen, Plug } from 'lucide-react'
import AgentKnowledgeBasesPanel from './AgentKnowledgeBasesPanel'
import AgentToolConnectionsPanel from './AgentToolConnectionsPanel'
import type { KnowledgeBaseSummary } from '../../knowledgeBases/knowledgeBaseTypes'

const TABS = [
  { id: 'connections', label: 'Connections', icon: Plug },
  { id: 'knowledge-bases', label: 'Knowledge bases', icon: BookOpen },
] as const

type ToolsTabId = (typeof TABS)[number]['id']

type ViewProps = {
  mode: 'view'
  agentId: string
  attachedKnowledgeBaseIds: string[]
  knowledgeBases: KnowledgeBaseSummary[]
}

type EditProps = {
  mode: 'edit'
  agentId?: string
  attachedKnowledgeBaseIds: string[]
  knowledgeBases: KnowledgeBaseSummary[]
  onKnowledgeBaseIdsChange: (ids: string[]) => void
}

export type ProductionAgentToolsSectionProps = ViewProps | EditProps

/** Production agent tool sources: external connections and knowledge bases (inner tabs, like Tools page). */
export default function ProductionAgentToolsSection(props: ProductionAgentToolsSectionProps) {
  const [tab, setTab] = useState<ToolsTabId>('connections')

  const { attachedKnowledgeBaseIds, knowledgeBases } = props

  return (
    <div className="space-y-4">
      <div className="flex gap-1 border-b border-gray-200" role="tablist" aria-label="Production agent tools">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${
              tab === id
                ? 'border-primary-500 text-gray-900'
                : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      <div className={tab === 'connections' ? undefined : 'hidden'}>
        {props.mode === 'view' || props.agentId ? (
          <AgentToolConnectionsPanel agentId={props.mode === 'view' ? props.agentId : props.agentId!} />
        ) : (
          <p className="text-sm text-gray-500">
            Save the agent first, then attach tool connections here.
          </p>
        )}
      </div>

      <div className={tab === 'knowledge-bases' ? undefined : 'hidden'}>
        {props.mode === 'view' ? (
          <AgentKnowledgeBasesPanel
            mode="view"
            side="production"
            attachedIds={attachedKnowledgeBaseIds}
            knowledgeBases={knowledgeBases}
          />
        ) : (
          <AgentKnowledgeBasesPanel
            mode="edit"
            side="production"
            attachedIds={attachedKnowledgeBaseIds}
            knowledgeBases={knowledgeBases}
            onChange={props.onKnowledgeBaseIdsChange}
          />
        )}
      </div>
    </div>
  )
}
