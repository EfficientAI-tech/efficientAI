import { create } from 'zustand'
import { apiClient } from '../lib/api'

/**
 * Auth store for the EfficientAI frontend.
 *
 * Supports two credential types in parallel:
 *   - Bearer access token (local password login or SSO). Preferred for humans.
 *   - API key (machine / legacy access). Kept for backward compatibility.
 *
 * Having either one populated makes the SPA treat the user as authenticated.
 * The API client prefers the Bearer token when both are set.
 */

type AuthUser = {
  id: string
  email: string
  name?: string | null
  first_name?: string | null
  last_name?: string | null
  organization_id: string
  role?: string | null
}

interface AuthState {
  apiKey: string | null
  accessToken: string | null
  user: AuthUser | null
  isLoading: boolean

  setApiKey: (key: string) => void
  setSession: (token: string, user: AuthUser) => void
  logout: () => void
  validate: () => Promise<boolean>
}

const STORAGE_API_KEY = 'apiKey'
const STORAGE_ACCESS_TOKEN = 'accessToken'
const STORAGE_USER = 'authUser'

function readStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_USER)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export const useAuthStore = create<AuthState>((set) => {
  const storedKey = localStorage.getItem(STORAGE_API_KEY)
  const storedToken = localStorage.getItem(STORAGE_ACCESS_TOKEN)

  if (storedKey) {
    apiClient.setApiKey(storedKey)
  }
  if (storedToken) {
    apiClient.setAccessToken(storedToken)
  }

  return {
    apiKey: storedKey,
    accessToken: storedToken,
    user: readStoredUser(),
    isLoading: false,

    setApiKey: (key: string) => {
      apiClient.setApiKey(key)
      localStorage.setItem(STORAGE_API_KEY, key)
      set({ apiKey: key })
    },

    setSession: (token: string, user: AuthUser) => {
      apiClient.setAccessToken(token)
      localStorage.setItem(STORAGE_ACCESS_TOKEN, token)
      localStorage.setItem(STORAGE_USER, JSON.stringify(user))
      set({ accessToken: token, user })
    },

    logout: () => {
      // Fire-and-forget: server is stateless for local tokens, but we still
      // hit /logout so future hooks (SSO backchannel, audit) can run.
      apiClient.logout().catch(() => {})
      apiClient.clearApiKey()
      apiClient.clearAccessToken()
      localStorage.removeItem(STORAGE_API_KEY)
      localStorage.removeItem(STORAGE_ACCESS_TOKEN)
      localStorage.removeItem(STORAGE_USER)
      set({ apiKey: null, accessToken: null, user: null })
    },

    validate: async () => {
      set({ isLoading: true })
      try {
        const result = await apiClient.validateApiKey()
        return result.valid
      } catch {
        return false
      } finally {
        set({ isLoading: false })
      }
    },
  }
})
