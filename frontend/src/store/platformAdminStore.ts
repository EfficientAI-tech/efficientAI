import { create } from 'zustand'
import { apiClient } from '../lib/api'

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

export const usePlatformAdminStore = create<PlatformAdminState>((set) => {
  const storedToken = localStorage.getItem(STORAGE_TOKEN)
  const storedAdmin = readStoredAdmin()

  return {
    accessToken: storedToken,
    admin: storedAdmin,
    setSession: (token, admin) => {
      localStorage.setItem(STORAGE_TOKEN, token)
      localStorage.setItem(STORAGE_ADMIN, JSON.stringify(admin))
      set({ accessToken: token, admin })
    },
    logout: () => {
      const clearLocal = () => {
        localStorage.removeItem(STORAGE_TOKEN)
        localStorage.removeItem(STORAGE_ADMIN)
        set({ accessToken: null, admin: null })
      }
      apiClient
        .platformLogout()
        .catch(() => apiClient.platformLogout())
        .finally(clearLocal)
    },
  }
})

export function isPlatformAdminAuthenticated(): boolean {
  return Boolean(localStorage.getItem(STORAGE_TOKEN))
}
