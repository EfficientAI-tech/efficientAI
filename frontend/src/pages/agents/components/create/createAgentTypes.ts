import type { TestAgentTemplateDraft } from '../agentTestSetupConstants'
import { defaultTestAgentTemplate } from '../agentTestSetupConstants'
import type { ChatIntegrationOptionId } from './ChatIntegrationTypeStep'

export type CreateAgentPath = 'telephony' | 'platform' | 'chat' | 'hosted'

export type AgentMedium = 'voice' | 'chat' | 'hosted'

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
  knowledge_base_ids: string[]
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
  knowledge_base_ids: [],
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

export const CHAT_STEPS_LLM = [
  { id: 1, title: 'Setup', description: 'Name and prompts' },
  { id: 2, title: 'Production LLM', description: 'API credential and model' },
  { id: 3, title: 'Test agent', description: 'LLM for simulated customer' },
] as const

/** Platform-hosted production agent (chat simulations today; voice later). */
export const HOSTED_STEPS = [
  { id: 1, title: 'Production agent', description: 'Brief and system prompt' },
  { id: 2, title: 'Test agent', description: 'Customer role from production' },
  { id: 3, title: 'Production LLM', description: 'Model that answers as production' },
  { id: 4, title: 'Test LLM', description: 'Model for simulated customer' },
] as const

/** Retell / Vapi / platform-linked chat agents */
export const CHAT_STEPS_PLATFORM = [
  { id: 1, title: 'Connect', description: 'Name and platform integration' },
  { id: 2, title: 'Prompts', description: 'Production prompt → test prompt' },
  { id: 3, title: 'Test agent', description: 'LLM for simulated customer' },
] as const

/** Customer HTTP API and messaging chat agents */
export const CHAT_STEPS_CONNECT = [
  { id: 1, title: 'Connect', description: 'Name and connection settings' },
  { id: 2, title: 'Prompts', description: 'Production prompt → test prompt' },
  { id: 3, title: 'Test agent', description: 'LLM for simulated customer' },
] as const

export function chatWizardNeedsLlmStep(integration: ChatIntegrationOptionId): boolean {
  return integration === 'internal_llm'
}

export function chatWizardSteps(integration: ChatIntegrationOptionId) {
  if (integration === 'internal_llm') return CHAT_STEPS_LLM
  if (integration === 'provider_chat') return CHAT_STEPS_PLATFORM
  return CHAT_STEPS_CONNECT
}

export function chatWizardMaxStep(_integration: ChatIntegrationOptionId): CreateStepId {
  return 3
}

export function createWizardMaxStep(path: CreateAgentPath): CreateStepId {
  if (path === 'hosted') return 4
  return 3
}

export type CreateStepId = 1 | 2 | 3 | 4
