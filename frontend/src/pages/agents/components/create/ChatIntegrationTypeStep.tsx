import { Brain, Cloud, Globe, MessagesSquare, type LucideIcon } from 'lucide-react'

import type { ChatConnectionType } from './ChatConnectionStep'
import { WizardStepHeader } from './WizardStepHeader'
import WizardIconCard from './WizardIconCard'
import {
  CHAT_CONNECTION_CAPABILITIES,
  type ChatIntegrationOptionId,
} from '../../../../lib/chatConnectionCapabilities'
import { WIZARD_EXISTING_PLATFORM_LABEL } from './wizardCopy'

export type { ChatIntegrationOptionId }

const ICONS: Record<ChatIntegrationOptionId, LucideIcon> = {
  internal_llm: Brain,
  provider_chat: Cloud,
  customer_api: Globe,
  messaging_channels: MessagesSquare,
}

const WIZARD_LABELS: Record<ChatIntegrationOptionId, string> = {
  internal_llm: 'LLM',
  provider_chat: WIZARD_EXISTING_PLATFORM_LABEL,
  customer_api: 'HTTP API',
  messaging_channels: 'Messaging',
}

interface ChatIntegrationTypeStepProps {
  value: ChatIntegrationOptionId
  onChange: (value: ChatIntegrationOptionId) => void
  embedded?: boolean
  compact?: boolean
}

export function isChatIntegrationAvailable(id: ChatIntegrationOptionId): boolean {
  return CHAT_CONNECTION_CAPABILITIES.some((c) => c.id === id && c.offeredInCreateWizard)
}

export function chatConnectionTypeFromOption(id: ChatIntegrationOptionId): ChatConnectionType {
  return id
}

export default function ChatIntegrationTypeStep({
  value,
  onChange,
  embedded,
  compact,
}: ChatIntegrationTypeStepProps) {
  const options = CHAT_CONNECTION_CAPABILITIES.filter((c) => c.offeredInCreateWizard)

  return (
    <div className={embedded ? 'w-full' : 'w-full max-w-3xl mx-auto space-y-6'}>
      {!embedded ? (
        <WizardStepHeader
          title="Chat connection"
          subtitle="How production replies on each eval turn."
          prominence={compact ? 'entry' : 'default'}
        />
      ) : null}
      <div
        className={`grid w-full ${
          compact
            ? 'grid-cols-1 gap-3.5 mt-4 sm:grid-cols-3'
            : 'grid-cols-1 sm:grid-cols-3 gap-3 mt-6 max-w-4xl'
        }`}
      >
        {options.map((option) => {
          const Icon = ICONS[option.id]
          const shortDesc = option.description.split('.')[0]
          return (
            <WizardIconCard
              key={option.id}
              label={WIZARD_LABELS[option.id]}
              subtitle={compact ? shortDesc : option.description}
              icon={Icon}
              selected={value === option.id}
              onSelect={() => onChange(option.id)}
              medium={!compact}
              compact={compact}
            />
          )
        })}
      </div>
    </div>
  )
}
