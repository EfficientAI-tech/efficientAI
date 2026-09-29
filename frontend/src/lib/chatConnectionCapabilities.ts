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
    label: 'LLM',
    description: 'LLM plays production; test agent is the customer.',
    pattern: 'llm_to_llm',
    offeredInCreateWizard: false,
  },
  {
    id: 'provider_chat',
    label: 'Existing platform',
    description: 'Retell, Vapi, ElevenLabs, or Smallest text chat.',
    pattern: 'live_production_plus_customer_llm',
    offeredInCreateWizard: true,
  },
  {
    id: 'customer_api',
    label: 'HTTP API',
    description: 'POST each turn to your REST API.',
    pattern: 'live_production_plus_customer_llm',
    offeredInCreateWizard: true,
  },
  {
    id: 'messaging_channels',
    label: 'Messaging',
    description: 'WhatsApp or SMS for production replies.',
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
  return pattern === 'llm_to_llm' ? 'LLM-to-LLM' : 'Live production + test agent'
}
