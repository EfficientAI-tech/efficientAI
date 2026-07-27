import type { LLMGenerationConfig } from '../config/llmGenerationParams'

export interface GenerateTestPromptParams {
  production_prompt: string
  agent_name: string
  language?: string
  call_type?: string
  provider?: string
  model?: string
  credential_id?: string
  llm_config?: LLMGenerationConfig | null
  additional_context?: string
}

export interface GenerateScenariosFromPromptParams {
  test_agent_prompt: string
  agent_name: string
  scenario_count?: number
  language?: string
  call_type?: string
  provider?: string
  model?: string
  credential_id?: string
  llm_config?: LLMGenerationConfig | null
  additional_context?: string
}

export interface GenerateTestSetupParams extends GenerateTestPromptParams {
  scenario_count?: number
}
