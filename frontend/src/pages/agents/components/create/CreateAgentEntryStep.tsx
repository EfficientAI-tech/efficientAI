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
  /** Modal entry: prominent step header + moderately sized choice cards. */
  compact?: boolean
}

export default function CreateAgentEntryStep({
  phase,
  agentMedium,
  onAgentMediumChange,
  voicePath,
  onVoicePathChange,
  chatIntegration,
  onChatIntegrationChange,
  compact = false,
}: CreateAgentEntryStepProps) {
  if (phase === 'entry_medium') {
    return (
      <AgentMediumStep
        value={agentMedium}
        onChange={onAgentMediumChange}
        embedded={false}
        compact={compact}
      />
    )
  }

  if (agentMedium === 'voice') {
    return (
      <VoicePathSelector
        value={voicePath === 'chat' ? 'telephony' : voicePath}
        onChange={onVoicePathChange}
        embedded={false}
        compact={compact}
      />
    )
  }

  if (agentMedium === 'chat') {
    return (
      <ChatIntegrationTypeStep
        value={chatIntegration}
        onChange={onChatIntegrationChange}
        embedded={false}
        compact={compact}
      />
    )
  }

  return null
}

export type { CreateWizardPhase }
