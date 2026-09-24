import { MODERN_INPUT_CLASS } from '../../evaluators/components/evaluatorUi'
import ChatConnectionStep, { type ChatConnectionForm } from './create/ChatConnectionStep'
import ChatConnectionDetailsStep, {
  type ChatConnectionConfigForm,
} from './create/ChatConnectionDetailsStep'
import type { ChatIntegrationOptionId } from './create/ChatIntegrationTypeStep'
import { connectionTypeLabel } from './create/chatAgentFormUtils'
import type { CreateAgentFormData } from './create/createAgentTypes'
import { defaultTestAgentTemplate } from './agentTestSetupConstants'
import { Integration, IntegrationPlatform } from '../../../types/api'

interface ChatAgentEditSectionProps {
  connectionType: string
  formData: Pick<CreateAgentFormData, 'voice_ai_integration_id' | 'voice_ai_agent_id'>
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
  if (t === 'provider_chat') return 'provider_chat'
  return 'internal_llm'
}

export default function ChatAgentEditSection({
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

  return (
    <div className="space-y-6 max-w-3xl">
      <p className="text-sm text-gray-600">
        Connection: <span className="font-medium text-gray-900">{connectionTypeLabel(connectionType)}</span>
      </p>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Production prompt</label>
        <textarea
          className={`${MODERN_INPUT_CLASS} min-h-[200px] font-mono text-xs`}
          value={providerPrompt}
          onChange={(e) => onProviderPromptChange(e.target.value)}
        />
      </div>

      {integrationType !== 'internal_llm' ? (
        <ChatConnectionDetailsStep
          integrationType={integrationType}
          formData={{
            name: '',
            phone_number: '',
            language: 'en',
            description: '',
            test_agent_template: defaultTestAgentTemplate(),
            call_type: 'outbound',
            call_medium: 'chat',
            telephony_phone_number_id: '',
            voice_bundle_id: '',
            voice_ai_integration_id: formData.voice_ai_integration_id,
            voice_ai_agent_id: formData.voice_ai_agent_id,
            silence_hangup_secs: 15,
          }}
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
      ) : null}

      <ChatConnectionStep
        value={chatConnection}
        onChange={onChatConnectionChange}
        variant="compact"
      />
    </div>
  )
}
