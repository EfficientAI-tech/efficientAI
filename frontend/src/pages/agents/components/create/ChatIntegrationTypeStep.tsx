import { Bot, Link2, Webhook, MessageCircle } from 'lucide-react'
import type { ChatConnectionType } from './ChatConnectionStep'
import { WizardStepHeader } from './WizardStepHeader'

export type ChatIntegrationOptionId =
  | ChatConnectionType
  | 'messaging_channels'

interface ChatIntegrationTypeStepProps {
  value: ChatIntegrationOptionId
  onChange: (value: ChatIntegrationOptionId) => void
  embedded?: boolean
}

const OPTIONS: {
  id: ChatIntegrationOptionId
  label: string
  description: string
  icon: typeof Bot
}[] = [
  {
    id: 'internal_llm',
    label: 'Platform LLM',
    description: 'Pre-prod simulation with your system prompt and EfficientAI LLMs.',
    icon: Bot,
  },
  {
    id: 'provider_chat',
    label: 'Provider live chat',
    description: 'Live text on Vapi, Retell, ElevenLabs, or Smallest.',
    icon: Link2,
  },
  {
    id: 'customer_api',
    label: 'HTTP API',
    description: 'Your own chat endpoint for production replies.',
    icon: Webhook,
  },
  {
    id: 'messaging_channels',
    label: 'Messaging',
    description: 'WhatsApp or SMS with webhook or carrier send for post-prod eval.',
    icon: MessageCircle,
  },
]

export function isChatIntegrationAvailable(id: ChatIntegrationOptionId): boolean {
  return (
    id === 'internal_llm' ||
    id === 'provider_chat' ||
    id === 'customer_api' ||
    id === 'messaging_channels'
  )
}

export function chatConnectionTypeFromOption(
  id: ChatIntegrationOptionId,
): 'internal_llm' | 'provider_chat' | 'customer_api' | 'messaging_channels' {
  if (id === 'messaging_channels') return 'messaging_channels'
  return id
}

export default function ChatIntegrationTypeStep({
  value,
  onChange,
  embedded,
}: ChatIntegrationTypeStepProps) {
  return (
    <div className={embedded ? 'w-full' : 'w-full max-w-3xl mx-auto space-y-6'}>
      {!embedded ? (
        <WizardStepHeader
          title="How does production chat connect?"
          subtitle="This drives the production leg in evaluation — simulation, live APIs, or imported transcripts later."
        />
      ) : null}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {OPTIONS.map((option) => {
          const Icon = option.icon
          const isSelected = value === option.id
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => onChange(option.id)}
              className={`text-left rounded-xl border-2 p-4 transition-colors ${
                isSelected
                  ? 'border-primary-600 bg-primary-50'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <div className="flex items-start gap-3">
                <div
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${
                    isSelected ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600'
                  }`}
                >
                  <Icon className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <span className="text-sm font-semibold text-gray-900 block">{option.label}</span>
                  <span className="text-xs text-gray-600 mt-1 block leading-relaxed">
                    {option.description}
                  </span>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
