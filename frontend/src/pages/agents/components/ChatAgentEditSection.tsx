import AIProviderModelPicker from '../../../components/AIProviderModelPicker'
import { OverviewSection } from './AgentOverviewLayout'
import ChatConnectionStep, { type ChatConnectionForm } from './create/ChatConnectionStep'
import ChatConnectionDetailsStep, {
  type ChatConnectionConfigForm,
} from './create/ChatConnectionDetailsStep'
import type { ChatIntegrationOptionId } from './create/ChatIntegrationTypeStep'
import { connectionTypeLabel } from './create/chatAgentFormUtils'
import type { CreateAgentFormData } from './create/createAgentTypes'
import { defaultTestAgentTemplate } from './agentTestSetupConstants'
import { Integration, IntegrationPlatform } from '../../../types/api'
import ChatPlatformConnectionFields from './chat/ChatPlatformConnectionFields'
import ChatProductionPromptEditor from './chat/ChatProductionPromptEditor'

interface ChatAgentEditSectionProps {
  mode: 'production' | 'test'
  connectionType: string
  formData: Pick<
    CreateAgentFormData,
    'voice_ai_integration_id' | 'voice_ai_agent_id' | 'name' | 'language' | 'call_type'
  >
  onFormChange: (patch: Partial<CreateAgentFormData>) => void
  providerPrompt: string
  onProviderPromptChange: (value: string) => void
  chatConnection: ChatConnectionForm
  onChatConnectionChange: (patch: Partial<ChatConnectionForm>) => void
  chatConfig: ChatConnectionConfigForm
  onChatConfigChange: (patch: Partial<ChatConnectionConfigForm>) => void
  integrations: Integration[]
  selectedPlatform: IntegrationPlatform | null
  onSelectPlatform: (p: IntegrationPlatform | null) => void
  showToast: (message: string, type: 'success' | 'error') => void
}

function integrationOptionFromType(type: string): ChatIntegrationOptionId {
  const t = (type || 'internal_llm').toLowerCase()
  if (t === 'messaging_channels') return 'messaging_channels'
  if (t === 'customer_api') return 'customer_api'
  if (t === 'customer_websocket') return 'customer_websocket'
  if (t === 'provider_chat') return 'provider_chat'
  return 'internal_llm'
}

const stubFormData = (
  formData: ChatAgentEditSectionProps['formData'],
): CreateAgentFormData => ({
  name: formData.name || '',
  phone_number: '',
  language: formData.language || 'en',
  description: '',
  test_agent_template: defaultTestAgentTemplate(),
  call_type: formData.call_type || 'outbound',
  call_medium: 'chat',
  telephony_phone_number_id: '',
  voice_bundle_id: '',
  voice_ai_integration_id: formData.voice_ai_integration_id,
  voice_ai_agent_id: formData.voice_ai_agent_id,
  silence_hangup_secs: 15,
})

export default function ChatAgentEditSection({
  mode,
  connectionType,
  formData,
  onFormChange,
  providerPrompt,
  onProviderPromptChange,
  chatConnection,
  onChatConnectionChange,
  chatConfig,
  onChatConfigChange,
  integrations,
  selectedPlatform,
  onSelectPlatform,
  showToast,
}: ChatAgentEditSectionProps) {
  const integrationType = integrationOptionFromType(connectionType)
  const connectionLabel = connectionTypeLabel(connectionType)

  if (mode === 'test') {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-5 max-w-3xl">
        <AIProviderModelPicker
          provider={chatConnection.testLlmProvider}
          model={chatConnection.testLlmModel}
          credentialId={chatConnection.testLlmCredentialId}
          onProviderChange={(provider) =>
            onChatConnectionChange({
              testLlmProvider: provider,
              testLlmModel: '',
              testLlmCredentialId: '',
            })
          }
          onModelChange={(model) => onChatConnectionChange({ testLlmModel: model })}
          onCredentialIdChange={(credentialId) =>
            onChatConnectionChange({ testLlmCredentialId: credentialId })
          }
          onSelectionChange={(next) =>
            onChatConnectionChange({
              testLlmProvider: next.provider,
              testLlmModel: next.model,
              testLlmCredentialId: next.credentialId,
            })
          }
          size="md"
          showAdvancedOptions={false}
        />
      </div>
    )
  }

  return (
    <div className="space-y-5 w-full max-w-4xl">
      {integrationType === 'provider_chat' ? (
        <OverviewSection title="Platform" description={`${connectionLabel} · production agent`}>
          <ChatPlatformConnectionFields
            integrations={integrations}
            selectedPlatform={selectedPlatform}
            onSelectPlatform={onSelectPlatform}
            voiceAiIntegrationId={formData.voice_ai_integration_id}
            voiceAiAgentId={formData.voice_ai_agent_id}
            onIntegrationChange={(id) => onFormChange({ voice_ai_integration_id: id, voice_ai_agent_id: '' })}
            onAgentIdChange={(id) => onFormChange({ voice_ai_agent_id: id })}
          />
        </OverviewSection>
      ) : null}

      {integrationType !== 'internal_llm' && integrationType !== 'provider_chat' ? (
        <OverviewSection title="Connection" description={connectionLabel}>
          <ChatConnectionDetailsStep
            variant="workspace"
            embedded
            integrationType={integrationType}
            formData={stubFormData(formData)}
            onFormChange={onFormChange}
            integrations={integrations}
            selectedPlatform={selectedPlatform}
            onSelectPlatform={onSelectPlatform}
            config={chatConfig}
            onConfigChange={onChatConfigChange}
            productionPrompt={providerPrompt}
            onProductionPromptChange={onProviderPromptChange}
            onPromptFetched={() => {}}
            showToast={showToast}
          />
        </OverviewSection>
      ) : null}

      {integrationType === 'internal_llm' ? (
        <OverviewSection title="Production model" description="LLM for the production chat leg.">
          <ChatConnectionStep
            value={chatConnection}
            onChange={onChatConnectionChange}
            variant="compact"
          />
        </OverviewSection>
      ) : null}

      <OverviewSection title="Production prompt" description="Scored in evaluators against the test agent.">
        <ChatProductionPromptEditor
          value={providerPrompt}
          onChange={onProviderPromptChange}
          showImportFromProvider={integrationType === 'provider_chat'}
          integrationId={formData.voice_ai_integration_id}
          agentId={formData.voice_ai_agent_id}
          showToast={showToast}
        />
      </OverviewSection>
    </div>
  )
}
