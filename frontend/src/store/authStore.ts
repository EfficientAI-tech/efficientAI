import { create } from 'zustand'
import { apiClient } from '../lib/api'

interface AuthState {
  apiKey: string | null
  isLoading: boolean
  setApiKey: (key: string) => void
  logout: () => void
  validateKey: () => Promise<boolean>
}

export const useAuthStore = create<AuthState>((set) => {
  // Load from localStorage on initialization
  const storedKey = localStorage.getItem('apiKey')
  if (storedKey) {
    apiClient.setApiKey(storedKey)
  }

  return {
    apiKey: storedKey,
    isLoading: false,
    setApiKey: (key: string) => {
      apiClient.setApiKey(key)
      localStorage.setItem('apiKey', key)
      set({ apiKey: key })
    },
    logout: () => {
      apiClient.clearApiKey()
      localStorage.removeItem('apiKey')
      set({ apiKey: null })
    },
    validateKey: async () => {
      set({ isLoading: true })
      try {
        const result = await apiClient.validateApiKey()
        return result.valid
      } catch (error) {
        return false
      } finally {
        set({ isLoading: false })
      }
    },
  }
})

