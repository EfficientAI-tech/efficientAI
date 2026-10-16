import AgentKnowledgeBasesPanel from '../AgentKnowledgeBasesPanel'
import type { KnowledgeBaseSummary } from '../../../knowledgeBases/knowledgeBaseTypes'
import ChatTestAgentLlmStep from './ChatTestAgentLlmStep'
import type { ChatConnectionForm } from './ChatConnectionStep'
import type { CreateAgentFormData } from './createAgentTypes'
import { assembleTestAgentPrompt, type TestAgentTemplateDraft } from '../agentTestSetupConstants'
import HostedWizardSplitLayout, { HostedPromptTextarea } from './HostedWizardSplitLayout'

interface HostedTestLlmStepProps {
  testAgentTemplate: TestAgentTemplateDraft
  formData: CreateAgentFormData
  onFormChange: (patch: Partial<CreateAgentFormData>) => void
  knowledgeBases: KnowledgeBaseSummary[]
  chatConnection: Pick<
    ChatConnectionForm,
    'testLlmProvider' | 'testLlmCredentialId' | 'testLlmModel'
  >
  onChatConnectionChange: (patch: Partial<ChatConnectionForm>) => void
}

export default function HostedTestLlmStep({
  testAgentTemplate,
  formData,
  onFormChange,
  knowledgeBases,
  chatConnection,
  onChatConnectionChange,
}: HostedTestLlmStepProps) {
  const assembled = assembleTestAgentPrompt(testAgentTemplate.sections)

  return (
    <HostedWizardSplitLayout
      title="Test LLM"
      subtitle="Runtime model for the simulated customer; assembled test prompt on the left."
      leftTitle="Assembled test agent prompt"
      leftHint="Read-only"
      left={<HostedPromptTextarea value={assembled} readOnly placeholder="—" />}
      right={
        <>
          <ChatTestAgentLlmStep embedded value={chatConnection} onChange={onChatConnectionChange} />
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
