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
        title="What are you evaluating?"
        subtitle="Start with voice or text chat, then choose how that agent runs in production."
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
            Pre-prod evaluation simulates your production chat agent with Platform LLM and a simulated customer.
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
