import { create } from 'zustand'
import { apiClient } from '../lib/api'
import { clearAuthSession } from '../lib/authSession'
import { useWorkspaceStore } from './workspaceStore'

type AuthUser = {
  id: string
  email: string
  name?: string | null
  first_name?: string | null
  last_name?: string | null
  organization_id: string
  role?: string | null
}

type SessionTokens = {
  access?: string
  refresh?: string
}

interface AuthState {
  apiKey: string | null
  accessToken: string | null
  refreshToken: string | null
  cookieSession: boolean
  user: AuthUser | null
  isLoading: boolean
  sessionReady: boolean

  setApiKey: (key: string) => void
  setSession: (user: AuthUser, tokens?: SessionTokens) => void
  switchOrg: (organizationId: string) => Promise<AuthUser>
  logout: () => void
  validate: () => Promise<boolean>
  bootstrapSession: () => Promise<void>
}

const STORAGE_API_KEY = 'apiKey'

function readStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem('authUser')
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

localStorage.removeItem('accessToken')
localStorage.removeItem('refreshToken')

export const useAuthStore = create<AuthState>((set, get) => {
  const storedKey = localStorage.getItem(STORAGE_API_KEY)
  if (storedKey) {
    apiClient.setApiKey(storedKey)
  }

  return {
    apiKey: storedKey,
    accessToken: null,
    refreshToken: null,
    cookieSession: false,
    user: readStoredUser(),
    isLoading: false,
    sessionReady: false,

    setApiKey: (key: string) => {
      apiClient.setApiKey(key)
      localStorage.setItem(STORAGE_API_KEY, key)
      set({ apiKey: key, cookieSession: false })
    },

    setSession: (user: AuthUser, tokens?: SessionTokens) => {
      apiClient.clearInMemoryTokens()
      if (tokens?.access) {
        apiClient.setAccessToken(tokens.access)
      }
      if (tokens?.refresh) {
        apiClient.setRefreshToken(tokens.refresh)
      }
      localStorage.setItem('authUser', JSON.stringify(user))
      set({
        accessToken: tokens?.access ?? null,
        refreshToken: tokens?.refresh ?? null,
        cookieSession: !tokens?.access && apiClient.isCookieSessionEnabled(),
        user,
        sessionReady: true,
      })
    },

    switchOrg: async (organizationId: string) => {
      const { access_token, refresh_token, user } = await apiClient.switchOrganization(organizationId)
      get().setSession(user, {
        access: access_token || undefined,
        refresh: refresh_token,
      })
      useWorkspaceStore.getState().clearActiveWorkspaceId()
      return user
    },

    logout: () => {
      const credentials = {
        accessToken: get().accessToken,
        refreshToken: get().refreshToken,
        apiKey: get().apiKey,
        cookieSession: get().cookieSession,
      }
      clearAuthSession()
      apiClient.clearInMemoryTokens()
      useWorkspaceStore.getState().clearActiveWorkspaceId()
      set({
        apiKey: null,
        accessToken: null,
        refreshToken: null,
        cookieSession: false,
        user: null,
        sessionReady: true,
      })
      apiClient.revokeUserSessionBestEffort(credentials)
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

    bootstrapSession: async () => {
      if (get().sessionReady) {
        return
      }
      if (get().apiKey) {
        set({ sessionReady: true, cookieSession: false })
        return
      }
      try {
        const config = await apiClient.getAuthConfig()
        apiClient.setCookieSessionEnabled(Boolean(config.cookie_session_enabled))
        const user = await apiClient.getMe()
        localStorage.setItem('authUser', JSON.stringify(user))
        set({
          user,
          cookieSession: Boolean(config.cookie_session_enabled),
          accessToken: null,
          refreshToken: null,
          sessionReady: true,
        })
      } catch {
        set({ sessionReady: true, user: null, cookieSession: false })
      }
    },
  }
})
