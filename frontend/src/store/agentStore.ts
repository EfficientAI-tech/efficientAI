import { create } from 'zustand'

export interface Agent {
  id: string
  agent_id?: string | null
  name: string
  phone_number: string
  language: string
  description: string | null
  call_type: string
  created_at: string
  updated_at: string
}

interface AgentState {
  selectedAgent: Agent | null
  setSelectedAgent: (agent: Agent | null) => void
  clearSelectedAgent: () => void
}

export const useAgentStore = create<AgentState>((set) => {
  // Load from localStorage on initialization
  const storedAgent = localStorage.getItem('selectedAgent')
  let initialAgent: Agent | null = null
  if (storedAgent) {
    try {
      initialAgent = JSON.parse(storedAgent)
    } catch {
      // Invalid JSON, ignore
    }
  }

  return {
    selectedAgent: initialAgent,
    setSelectedAgent: (agent) => {
      if (agent) {
        localStorage.setItem('selectedAgent', JSON.stringify(agent))
      } else {
        localStorage.removeItem('selectedAgent')
      }
      set({ selectedAgent: agent })
    },
    clearSelectedAgent: () => {
      localStorage.removeItem('selectedAgent')
      set({ selectedAgent: null })
    },
  }
})

