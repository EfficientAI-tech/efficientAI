import type { ExpectedToolCall } from '../../types/api'

export interface Scenario {
  id: string
  name: string
  agent_id?: string | null
  description: string | null
  required_info: Record<string, string>
  expected_tool_calls?: ExpectedToolCall[] | null
  created_at: string
  updated_at: string
  created_by?: string | null
}

export interface AgentOption {
  id: string
  name: string
  description?: string | null
  provider_prompt?: string | null
  language?: string
  call_type?: string
  call_medium?: string
}
