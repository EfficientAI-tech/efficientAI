import AgentMediumStep from './AgentMediumStep'
import VoicePathSelector from './VoicePathSelector'
import ChatIntegrationTypeStep, { type ChatIntegrationOptionId } from './ChatIntegrationTypeStep'
import type { AgentMedium, CreateAgentPath, CreateWizardPhase } from './createAgentTypes'

interface CreateAgentEntryStepProps {
  phase: 'entry_medium' | 'entry_integration'
  agentMedium: AgentMedium | null
  onAgentMediumChange: (medium: AgentMedium) => void
  voicePath: CreateAgentPath
  onVoicePathChange: (path: CreateAgentPath) => void
  chatIntegration: ChatIntegrationOptionId
  onChatIntegrationChange: (option: ChatIntegrationOptionId) => void
}

export default function CreateAgentEntryStep({
  phase,
  agentMedium,
  onAgentMediumChange,
  voicePath,
  onVoicePathChange,
  chatIntegration,
  onChatIntegrationChange,
}: CreateAgentEntryStepProps) {
  if (phase === 'entry_medium') {
    return <AgentMediumStep value={agentMedium} onChange={onAgentMediumChange} />
  }

  if (agentMedium === 'voice') {
    return (
      <VoicePathSelector
        value={voicePath === 'chat' ? 'telephony' : voicePath}
        onChange={onVoicePathChange}
      />
    )
  }

  if (agentMedium === 'chat') {
    return (
      <ChatIntegrationTypeStep value={chatIntegration} onChange={onChatIntegrationChange} />
    )
  }

  return null
}

export type { CreateWizardPhase }
