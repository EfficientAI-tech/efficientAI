import { create } from 'zustand'
import { apiClient } from '../lib/api'
import { clearPlatformAdminSession } from '../lib/authSession'

type PlatformAdminUser = {
  id: string
  email: string
}

interface PlatformAdminState {
  accessToken: string | null
  admin: PlatformAdminUser | null
  setSession: (token: string, admin: PlatformAdminUser) => void
  logout: () => void
}

const STORAGE_TOKEN = 'platformAccessToken'
const STORAGE_ADMIN = 'platformAdminUser'

function readStoredAdmin(): PlatformAdminUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_ADMIN)
    return raw ? (JSON.parse(raw) as PlatformAdminUser) : null
  } catch {
    return null
  }
}

export const usePlatformAdminStore = create<PlatformAdminState>((set, get) => {
  const storedToken = localStorage.getItem(STORAGE_TOKEN)
  const storedAdmin = readStoredAdmin()

  return {
    accessToken: storedToken,
    admin: storedAdmin,
    setSession: (token, admin) => {
      if (token) {
        localStorage.setItem(STORAGE_TOKEN, token)
      } else {
        localStorage.removeItem(STORAGE_TOKEN)
      }
      localStorage.setItem(STORAGE_ADMIN, JSON.stringify(admin))
      set({ accessToken: token || null, admin })
    },
    logout: () => {
      const accessToken = get().accessToken
      clearPlatformAdminSession()
      set({ accessToken: null, admin: null })
      apiClient.revokePlatformSessionBestEffort(accessToken)
    },
  }
})

export function isPlatformAdminAuthenticated(): boolean {
  const state = usePlatformAdminStore.getState()
  return Boolean(state.accessToken || state.admin)
}
