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
import PlatformConnectStep from './create/PlatformConnectStep'
import { ChatProviderPromptBlock } from './create/ChatConnectionDetailsStep'
import { NATIVE_PROVIDER_TEXT_CHAT_PLATFORMS } from '../../../lib/chatConnectionCapabilities'

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
  if (t === 'provider_chat') return 'provider_chat'
  return 'internal_llm'
}

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

  if (mode === 'test') {
    return (
      <p className="text-sm text-gray-600 max-w-3xl">
        Configure the <span className="font-medium text-gray-800">simulated customer</span> (bundle LLM +
        template). Your production chat agent is on the <span className="font-medium text-gray-800">Chat Agent</span>{' '}
        tab — nothing here changes production.
      </p>
    )
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <p className="text-sm text-gray-600">
        Production agent under test —{' '}
        <span className="font-medium text-gray-900">{connectionTypeLabel(connectionType)}</span>
      </p>

      {integrationType === 'provider_chat' ? (
        <PlatformConnectStep
          showNameField={false}
          integrations={integrations}
          agentName={formData.name}
          onAgentNameChange={() => {}}
          selectedPlatform={selectedPlatform}
          onSelectPlatform={onSelectPlatform}
          voiceAiIntegrationId={formData.voice_ai_integration_id}
          voiceAiAgentId={formData.voice_ai_agent_id}
          onIntegrationChange={(id) => onFormChange({ voice_ai_integration_id: id })}
          onAgentIdChange={(id) => onFormChange({ voice_ai_agent_id: id })}
          introTitle="Existing platform integration"
          introSubtitle="External chat agent on Vapi, Retell, ElevenLabs, or Smallest."
          platformOptions={NATIVE_PROVIDER_TEXT_CHAT_PLATFORMS}
          remoteAgentKind="chat"
        />
      ) : null}

      {integrationType !== 'internal_llm' && integrationType !== 'provider_chat' ? (
        <ChatConnectionDetailsStep
          integrationType={integrationType}
          formData={{
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

      {integrationType === 'internal_llm' ? (
        <ChatConnectionStep
          value={chatConnection}
          onChange={onChatConnectionChange}
          variant="compact"
        />
      ) : null}

      {integrationType === 'provider_chat' ? (
        <ChatProviderPromptBlock
          formData={{
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
          }}
          productionPrompt={providerPrompt}
          onProductionPromptChange={onProviderPromptChange}
          onPromptFetched={() => {}}
          showToast={showToast}
        />
      ) : (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Production prompt *</label>
          <textarea
            className={`${MODERN_INPUT_CLASS} min-h-[200px] font-mono text-xs`}
            value={providerPrompt}
            onChange={(e) => onProviderPromptChange(e.target.value)}
            placeholder="Instructions scored against in evals…"
          />
        </div>
      )}
    </div>
  )
}
