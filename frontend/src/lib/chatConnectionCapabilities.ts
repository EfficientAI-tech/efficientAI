import type { ChatConnectionType } from '../pages/agents/components/create/ChatConnectionStep'
import { IntegrationPlatform } from '../types/api'

export type ChatIntegrationOptionId = ChatConnectionType

/** Both conversation legs use your configured LLMs (no external production channel). */
export type ChatEvalPattern = 'llm_to_llm' | 'live_production_plus_customer_llm'

export type ChatConnectionCapability = {
  id: ChatIntegrationOptionId
  label: string
  description: string
  pattern: ChatEvalPattern
  /** Shown in create-agent UI (backend may still accept others via API). */
  offeredInCreateWizard: boolean
}

/**
 * Mirrors app/services/testing/llm_to_llm_evaluator_simulation.py and
 * app/services/agents/chat_production_leg.py + provider_platform_chat.py.
 */
export const CHAT_CONNECTION_CAPABILITIES: ChatConnectionCapability[] = [
  {
    id: 'internal_llm',
    label: 'Platform LLM',
    description:
      'Your production prompt is the agent on Platform LLM; a test LLM plays the other side (like voice test agents).',
    pattern: 'llm_to_llm',
    offeredInCreateWizard: true,
  },
  {
    id: 'provider_chat',
    label: 'Provider live chat',
    description:
      'Not LLM-to-LLM for the agent: each turn hits the provider text chat API (Vapi, Retell, ElevenLabs, or Smallest). The customer side is still an LLM.',
    pattern: 'live_production_plus_customer_llm',
    offeredInCreateWizard: true,
  },
  {
    id: 'customer_api',
    label: 'HTTP API',
    description:
      'Not LLM-to-LLM for the agent: your HTTP endpoint answers each turn. The customer side is an LLM.',
    pattern: 'live_production_plus_customer_llm',
    offeredInCreateWizard: true,
  },
  {
    id: 'messaging_channels',
    label: 'Messaging',
    description:
      'Not LLM-to-LLM for the agent: WhatsApp/SMS or webhooks for production replies. The customer side is an LLM.',
    pattern: 'live_production_plus_customer_llm',
    offeredInCreateWizard: true,
  },
]

export const NATIVE_PROVIDER_TEXT_CHAT_PLATFORMS: IntegrationPlatform[] = [
  IntegrationPlatform.VAPI,
  IntegrationPlatform.RETELL,
  IntegrationPlatform.ELEVENLABS,
  IntegrationPlatform.SMALLEST,
]

export function chatConnectionCapability(
  id: ChatIntegrationOptionId | string,
): ChatConnectionCapability | undefined {
  return CHAT_CONNECTION_CAPABILITIES.find((c) => c.id === id)
}

export function isFullLlmToLlmChatConnection(id: ChatIntegrationOptionId | string): boolean {
  return chatConnectionCapability(id)?.pattern === 'llm_to_llm'
}

export function createWizardChatConnections(): ChatConnectionCapability[] {
  return CHAT_CONNECTION_CAPABILITIES.filter((c) => c.offeredInCreateWizard)
}

export function patternLabel(pattern: ChatEvalPattern): string {
  return pattern === 'llm_to_llm' ? 'LLM-to-LLM' : 'Live production + test LLM'
}
