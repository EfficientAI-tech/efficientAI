import type { TestAgentTemplateDraft } from '../agentTestSetupConstants'
import { defaultTestAgentTemplate } from '../agentTestSetupConstants'

export type CreateAgentPath = 'telephony' | 'platform' | 'chat'

export type AgentMedium = 'voice' | 'chat'

export type CreateWizardPhase = 'medium' | 'voice-path' | 'steps'

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
  { id: 2, title: 'Voice', description: 'Select voice bundle' },
  { id: 3, title: 'Prompts', description: 'Imported prompt → test prompt' },
] as const

export const CHAT_STEPS = [
  { id: 1, title: 'Connect', description: 'Production chat integration' },
  { id: 2, title: 'Agent', description: 'Identity, platform, prompt' },
  { id: 3, title: 'Pre-prod eval', description: 'Evaluator LLMs & mode' },
] as const

export type CreateStepId = 1 | 2 | 3
