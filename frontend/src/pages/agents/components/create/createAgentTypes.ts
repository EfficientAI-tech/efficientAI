export type CreateAgentPath = 'telephony' | 'platform'

export interface CreateAgentFormData {
  name: string
  phone_number: string
  language: string
  description: string
  call_type: string
  call_medium: 'phone_call'
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
  { id: 1, title: 'Connect', description: 'Choose platform, integration, Agent ID' },
  { id: 2, title: 'Voice', description: 'Select voice bundle' },
  { id: 3, title: 'Prompts', description: 'Imported prompt → test prompt' },
] as const

export type CreateStepId = 1 | 2 | 3
