import { create } from 'zustand'
import { apiClient } from '../lib/api'
import { useWorkspaceStore } from './workspaceStore'

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
  refreshToken: string | null
  user: AuthUser | null
  isLoading: boolean

  setApiKey: (key: string) => void
  setSession: (token: string, user: AuthUser, refreshToken?: string | null) => void
  switchOrg: (organizationId: string) => Promise<AuthUser>
  logout: () => void
  validate: () => Promise<boolean>
}

const STORAGE_API_KEY = 'apiKey'
const STORAGE_ACCESS_TOKEN = 'accessToken'
const STORAGE_REFRESH_TOKEN = 'refreshToken'
const STORAGE_USER = 'authUser'

function readStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_USER)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export const useAuthStore = create<AuthState>((set, get) => {
  const storedKey = localStorage.getItem(STORAGE_API_KEY)
  const storedToken = localStorage.getItem(STORAGE_ACCESS_TOKEN)
  const storedRefreshToken = localStorage.getItem(STORAGE_REFRESH_TOKEN)

  if (storedKey) {
    apiClient.setApiKey(storedKey)
  }
  if (storedToken) {
    apiClient.setAccessToken(storedToken)
  }
  if (storedRefreshToken) {
    apiClient.setRefreshToken(storedRefreshToken)
  }

  return {
    apiKey: storedKey,
    accessToken: storedToken,
    refreshToken: storedRefreshToken,
    user: readStoredUser(),
    isLoading: false,

    setApiKey: (key: string) => {
      apiClient.setApiKey(key)
      localStorage.setItem(STORAGE_API_KEY, key)
      set({ apiKey: key })
    },

    setSession: (token: string, user: AuthUser, refreshToken?: string | null) => {
      apiClient.setAccessToken(token)
      localStorage.setItem(STORAGE_ACCESS_TOKEN, token)
      localStorage.setItem(STORAGE_USER, JSON.stringify(user))
      if (refreshToken) {
        apiClient.setRefreshToken(refreshToken)
        localStorage.setItem(STORAGE_REFRESH_TOKEN, refreshToken)
      }
      set({
        accessToken: token,
        refreshToken: refreshToken ?? get().refreshToken,
        user,
      })
    },

    switchOrg: async (organizationId: string) => {
      const { access_token, refresh_token, user } = await apiClient.switchOrganization(organizationId)
      apiClient.setAccessToken(access_token)
      localStorage.setItem(STORAGE_ACCESS_TOKEN, access_token)
      localStorage.setItem(STORAGE_USER, JSON.stringify(user))
      if (refresh_token) {
        apiClient.setRefreshToken(refresh_token)
        localStorage.setItem(STORAGE_REFRESH_TOKEN, refresh_token)
      }
      useWorkspaceStore.getState().clearActiveWorkspaceId()
      set({
        accessToken: access_token,
        refreshToken: refresh_token ?? get().refreshToken,
        user,
      })
      return user
    },

    logout: () => {
      const refreshToken = get().refreshToken
      apiClient.logout(refreshToken).catch(() => {})
      apiClient.clearApiKey()
      apiClient.clearAccessToken()
      apiClient.clearRefreshToken()
      localStorage.removeItem(STORAGE_API_KEY)
      localStorage.removeItem(STORAGE_ACCESS_TOKEN)
      localStorage.removeItem(STORAGE_REFRESH_TOKEN)
      localStorage.removeItem(STORAGE_USER)
      useWorkspaceStore.getState().clearActiveWorkspaceId()
      set({ apiKey: null, accessToken: null, refreshToken: null, user: null })
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
