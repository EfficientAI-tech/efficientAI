import AgentKnowledgeBasesPanel from '../AgentKnowledgeBasesPanel'
import type { KnowledgeBaseSummary } from '../../../knowledgeBases/knowledgeBaseTypes'
import ChatConnectionStep, { type ChatConnectionForm } from './ChatConnectionStep'
import type { CreateAgentFormData } from './createAgentTypes'
import HostedWizardSplitLayout, { HostedPromptTextarea } from './HostedWizardSplitLayout'

interface HostedProductionLlmStepProps {
  productionPrompt: string
  formData: CreateAgentFormData
  onFormChange: (patch: Partial<CreateAgentFormData>) => void
  knowledgeBases: KnowledgeBaseSummary[]
  chatConnection: ChatConnectionForm
  onChatConnectionChange: (patch: Partial<ChatConnectionForm>) => void
}

export default function HostedProductionLlmStep({
  productionPrompt,
  formData,
  onFormChange,
  knowledgeBases,
  chatConnection,
  onChatConnectionChange,
}: HostedProductionLlmStepProps) {
  return (
    <HostedWizardSplitLayout
      title="Production LLM"
      subtitle="Runtime model for the production leg; prompt preview on the left."
      leftTitle="Production system prompt"
      leftHint="Read-only"
      left={
        <HostedPromptTextarea value={productionPrompt} readOnly placeholder="—" />
      }
      right={
        <>
          <ChatConnectionStep
            value={chatConnection}
            onChange={onChatConnectionChange}
          />
          <AgentKnowledgeBasesPanel
            compact
            mode="edit"
            attachedIds={formData.knowledge_base_ids}
            knowledgeBases={knowledgeBases}
            onChange={(ids) => onFormChange({ knowledge_base_ids: ids })}
          />
        </>
      }
    />
  )
}
