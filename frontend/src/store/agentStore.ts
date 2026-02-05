import { create } from 'zustand'
import { apiClient } from '../lib/api'

export interface Agent {
  id: string
  agent_id?: string | null
  name: string
  phone_number?: string | null
  language: string
  description: string | null
  call_type: string
  call_medium?: string
  voice_bundle_id?: string | null
  voice_ai_integration_id?: string | null
  voice_ai_agent_id?: string | null
  created_at: string
  updated_at: string
}

interface AgentState {
  selectedAgent: Agent | null
  isLoading: boolean
  isInitialized: boolean
  setSelectedAgent: (agent: Agent | null) => void
  clearSelectedAgent: () => void
  loadPreferences: () => Promise<void>
}

export const useAgentStore = create<AgentState>((set, get) => {
  // Load from localStorage as initial cache (for faster initial render)
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
    isLoading: false,
    isInitialized: false,
    
    setSelectedAgent: async (agent) => {
      // Update local state immediately for responsive UI
      if (agent) {
        localStorage.setItem('selectedAgent', JSON.stringify(agent))
      } else {
        localStorage.removeItem('selectedAgent')
      }
      set({ selectedAgent: agent })
      
      // Sync to backend (fire and forget, don't block UI)
      try {
        await apiClient.updateUserPreferences({
          default_agent_id: agent?.id || null
        })
      } catch (error) {
        console.warn('Failed to sync agent preference to backend:', error)
        // Don't throw - local state is already updated
      }
    },
    
    clearSelectedAgent: async () => {
      localStorage.removeItem('selectedAgent')
      set({ selectedAgent: null })
      
      // Sync to backend
      try {
        await apiClient.updateUserPreferences({
          default_agent_id: null
        })
      } catch (error) {
        console.warn('Failed to clear agent preference on backend:', error)
      }
    },
    
    loadPreferences: async () => {
      // Don't reload if already initialized and not loading
      if (get().isInitialized) return
      
      set({ isLoading: true })
      try {
        const preferences = await apiClient.getUserPreferences()
        
        if (preferences.default_agent) {
          // Convert the backend agent format to our store format
          const agent: Agent = {
            id: preferences.default_agent.id,
            agent_id: preferences.default_agent.agent_id,
            name: preferences.default_agent.name,
            phone_number: preferences.default_agent.phone_number,
            language: preferences.default_agent.language,
            description: preferences.default_agent.description,
            call_type: preferences.default_agent.call_type,
            call_medium: preferences.default_agent.call_medium,
            created_at: '', // Not provided by preferences endpoint
            updated_at: ''
          }
          localStorage.setItem('selectedAgent', JSON.stringify(agent))
          set({ selectedAgent: agent, isLoading: false, isInitialized: true })
        } else {
          // No default agent set on backend
          localStorage.removeItem('selectedAgent')
          set({ selectedAgent: null, isLoading: false, isInitialized: true })
        }
      } catch (error) {
        console.warn('Failed to load preferences from backend, using localStorage cache:', error)
        // Keep using localStorage cache on error
        set({ isLoading: false, isInitialized: true })
      }
    }
  }
})

