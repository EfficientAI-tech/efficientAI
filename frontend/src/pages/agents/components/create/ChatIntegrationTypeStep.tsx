import { Brain, Cable, Cloud, Globe, MessagesSquare, type LucideIcon } from 'lucide-react'

import type { ChatConnectionType } from './ChatConnectionStep'
import { WizardStepHeader } from './WizardStepHeader'
import WizardIconCard from './WizardIconCard'
import {
  CHAT_CONNECTION_CAPABILITIES,
  type ChatIntegrationOptionId,
} from '../../../../lib/chatConnectionCapabilities'
import { WIZARD_EXISTING_PLATFORM_LABEL, wizardOptionGridClass } from './wizardCopy'
import { useLicenseStore } from '../../../../store/licenseStore'

export type { ChatIntegrationOptionId }

const ICONS: Record<ChatIntegrationOptionId, LucideIcon> = {
  internal_llm: Brain,
  provider_chat: Cloud,
  customer_api: Globe,
  customer_websocket: Cable,
  messaging_channels: MessagesSquare,
}

const WIZARD_LABELS: Record<ChatIntegrationOptionId, string> = {
  internal_llm: 'Hosted agent',
  provider_chat: WIZARD_EXISTING_PLATFORM_LABEL,
  customer_api: 'HTTP API',
  customer_websocket: 'WebSocket',
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
  const { isFeatureEnabled, isLoaded } = useLicenseStore()
  const hostedEnabled = !isLoaded || isFeatureEnabled('hosted_agents')
  const options = CHAT_CONNECTION_CAPABILITIES.filter(
    (c) =>
      c.offeredInCreateWizard &&
      (c.id !== 'internal_llm' || hostedEnabled),
  )
  const gridClass = wizardOptionGridClass(
    options.length,
    Boolean(compact),
  )

  return (
    <div className={embedded ? 'w-full' : 'w-full max-w-3xl mx-auto space-y-6'}>
      {!embedded ? (
        <WizardStepHeader
          title="Chat connection"
          subtitle="How production replies on each eval turn."
          prominence={compact ? 'entry' : 'default'}
        />
      ) : null}
      <div className={`${gridClass}${compact ? '' : ' max-w-4xl'}`}>
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
