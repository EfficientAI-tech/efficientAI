export interface Scenario {
  id: string
  name: string
  agent_id?: string | null
  description: string | null
  required_info: Record<string, string>
  created_at: string
  updated_at: string
  created_by?: string | null
}

export interface AgentOption {
  id: string
  name: string
  description?: string | null
  language?: string
  call_type?: string
}
