import { create } from 'zustand'

const STORAGE_KEY = 'dashboardMockData.v1'

/**
 * Sample data is on by default until live/simulation scoring is wired for
 * every workspace. Flip this to false to make real data the default.
 */
const MOCK_DATA_DEFAULT = true

function readInitial(): boolean {
  if (typeof window === 'undefined') return MOCK_DATA_DEFAULT
  const fromUrl = new URLSearchParams(window.location.search).get('mock')
  if (fromUrl === '1' || fromUrl === 'true') return true
  if (fromUrl === '0' || fromUrl === 'false') return false
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'true') return true
  if (stored === 'false') return false
  return MOCK_DATA_DEFAULT
}

interface MockDataState {
  enabled: boolean
  setEnabled: (enabled: boolean) => void
}

export const useMockDataStore = create<MockDataState>((set) => ({
  enabled: readInitial(),
  setEnabled: (enabled) => {
    if (typeof window !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, String(enabled))
    }
    set({ enabled })
  },
}))

export function isMockDataEnabled(): boolean {
  return useMockDataStore.getState().enabled
}
