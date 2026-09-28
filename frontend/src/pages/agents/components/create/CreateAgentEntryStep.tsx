import AgentMediumStep from './AgentMediumStep'
import VoicePathSelector from './VoicePathSelector'
import ChatIntegrationTypeStep, { type ChatIntegrationOptionId } from './ChatIntegrationTypeStep'
import { WizardStepHeader } from './WizardStepHeader'
import type { AgentMedium, CreateAgentPath } from './createAgentTypes'

interface CreateAgentEntryStepProps {
  agentMedium: AgentMedium | null
  onAgentMediumChange: (medium: AgentMedium) => void
  voicePath: CreateAgentPath
  onVoicePathChange: (path: CreateAgentPath) => void
  chatIntegration: ChatIntegrationOptionId
  onChatIntegrationChange: (option: ChatIntegrationOptionId) => void
}

export default function CreateAgentEntryStep({
  agentMedium,
  onAgentMediumChange,
  voicePath,
  onVoicePathChange,
  chatIntegration,
  onChatIntegrationChange,
}: CreateAgentEntryStepProps) {
  return (
    <div className="w-full max-w-2xl mx-auto space-y-8 pb-2">
      <WizardStepHeader
        title="Create agent"
        subtitle="One flow for voice and text chat — pick a medium, then configure only what applies."
      />

      <section className="space-y-3">
        <h3 className="text-sm font-medium text-gray-900">Agent medium</h3>
        <AgentMediumStep embedded value={agentMedium} onChange={onAgentMediumChange} />
      </section>

      {agentMedium === 'voice' ? (
        <section className="space-y-3 pt-2 border-t border-gray-100">
          <h3 className="text-sm font-medium text-gray-900">Voice deployment</h3>
          <p className="text-sm text-gray-600 leading-relaxed">
            Phone numbers and carriers, or an agent hosted on Vapi, Retell, and similar platforms.
          </p>
          <VoicePathSelector
            embedded
            value={voicePath === 'chat' ? 'telephony' : voicePath}
            onChange={onVoicePathChange}
          />
        </section>
      ) : null}

      {agentMedium === 'chat' ? (
        <section className="space-y-3 pt-2 border-t border-gray-100">
          <h3 className="text-sm font-medium text-gray-900">Chat connection</h3>
          <p className="text-sm text-gray-600 leading-relaxed">
            Platform LLM is full LLM-to-LLM on our models. Other options use your live stack each turn.
          </p>
          <ChatIntegrationTypeStep
            embedded
            value={chatIntegration}
            onChange={onChatIntegrationChange}
          />
        </section>
      ) : null}

      {!agentMedium ? (
        <p className="text-sm text-gray-500 border-t border-gray-100 pt-6">
          Select voice or text chat to see deployment options.
        </p>
      ) : null}
    </div>
  )
}
