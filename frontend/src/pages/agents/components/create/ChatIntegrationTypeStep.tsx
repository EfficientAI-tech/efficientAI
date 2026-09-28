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
}: ChatIntegrationTypeStepProps) {
  const options = CHAT_CONNECTION_CAPABILITIES.filter((c) => c.offeredInCreateWizard)

  return (
    <div className={embedded ? 'w-full' : 'w-full max-w-3xl mx-auto space-y-6'}>
      {!embedded ? (
        <WizardStepHeader title="Chat connection" subtitle="How the production agent is reached each turn." />
      ) : null}
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Chat</p>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 w-full max-w-4xl">
        {options.map((option) => {
          const Icon = ICONS[option.id]
          return (
            <WizardIconCard
              key={option.id}
              label={WIZARD_LABELS[option.id]}
              icon={Icon}
              selected={value === option.id}
              onSelect={() => onChange(option.id)}
            />
          )
        })}
      </div>
    </div>
  )
}
