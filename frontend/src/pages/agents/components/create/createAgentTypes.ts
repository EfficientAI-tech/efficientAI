import type { TestAgentTemplateDraft } from '../agentTestSetupConstants'
import { defaultTestAgentTemplate } from '../agentTestSetupConstants'
import type { ChatIntegrationOptionId } from './ChatIntegrationTypeStep'

export type CreateAgentPath = 'telephony' | 'platform' | 'chat'

export type AgentMedium = 'voice' | 'chat'

export type CreateWizardPhase = 'entry_medium' | 'entry_integration' | 'steps'

export interface CreateAgentFormData {
  name: string
  phone_number: string
  language: string
  description: string
  test_agent_template: TestAgentTemplateDraft
  call_type: string
  call_medium: 'phone_call' | 'web_call' | 'chat'
  telephony_phone_number_id: string
  voice_bundle_id: string
  voice_ai_integration_id: string
  voice_ai_agent_id: string
  silence_hangup_secs: number
}

export const DEFAULT_CREATE_AGENT_FORM: CreateAgentFormData = {
  name: '',
  phone_number: '',
  language: 'en',
  description: '',
  test_agent_template: defaultTestAgentTemplate(),
  call_type: 'outbound',
  call_medium: 'phone_call',
  telephony_phone_number_id: '',
  voice_bundle_id: '',
  voice_ai_integration_id: '',
  voice_ai_agent_id: '',
  silence_hangup_secs: 15,
}

export const TELEPHONY_STEPS = [
  { id: 1, title: 'Telephony', description: 'Name, number, direction, silence' },
  { id: 2, title: 'Prompts', description: 'Production prompt → test prompt' },
  { id: 3, title: 'Voice', description: 'Select voice bundle' },
] as const

export const PLATFORM_STEPS = [
  { id: 1, title: 'Connect', description: 'Choose platform, integration, agent' },
  { id: 2, title: 'Prompts', description: 'Imported prompt → test prompt' },
  { id: 3, title: 'Voice', description: 'Select voice bundle' },
] as const

export const CHAT_STEPS = [
  { id: 1, title: 'Connect', description: 'Name, chat connection, and provider' },
  { id: 2, title: 'Prompts', description: 'Production prompt and test agent template' },
  { id: 3, title: 'Chat agent LLM', description: 'API credential and model (production leg)' },
] as const

export const CHAT_STEPS_TWO_STEP = CHAT_STEPS.filter((s) => s.id !== 3)

export function chatWizardNeedsLlmStep(integration: ChatIntegrationOptionId): boolean {
  return integration === 'internal_llm'
}

export function chatWizardSteps(integration: ChatIntegrationOptionId) {
  if (chatWizardNeedsLlmStep(integration)) return CHAT_STEPS
  return CHAT_STEPS_TWO_STEP
}

export function chatWizardMaxStep(integration: ChatIntegrationOptionId): CreateStepId {
  return chatWizardNeedsLlmStep(integration) ? 3 : 2
}

/** Chat create: link first active bundle for eval customer LLM (no wizard step). */
export function defaultVoiceBundleIdForChat(
  bundles: { id: string; is_active?: boolean }[],
): string {
  const active = bundles.filter((b) => b.is_active !== false)
  return active[0]?.id ?? ''
}

export function createWizardMaxStep(_path: CreateAgentPath): CreateStepId {
  return 3
}

export type CreateStepId = 1 | 2 | 3
