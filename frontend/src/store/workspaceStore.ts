import { create } from 'zustand'

const STORAGE_WORKSPACE_ID = 'activeWorkspaceId'

interface WorkspaceState {
  activeWorkspaceId: string | null
  activeCapabilities: string[]
  setActiveWorkspaceId: (id: string | null) => void
  setActiveCapabilities: (capabilities: string[]) => void
  switchWorkspace: (id: string, capabilities?: string[]) => void
  clearActiveWorkspaceId: () => void
}

function readStored(): string | null {
  try {
    return localStorage.getItem(STORAGE_WORKSPACE_ID)
  } catch {
    return null
  }
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  activeWorkspaceId: readStored(),
  activeCapabilities: [],

  setActiveWorkspaceId: (id: string | null) => {
    if (id) {
      localStorage.setItem(STORAGE_WORKSPACE_ID, id)
    } else {
      localStorage.removeItem(STORAGE_WORKSPACE_ID)
    }
    set({ activeWorkspaceId: id })
  },

  setActiveCapabilities: (capabilities: string[]) => {
    set({ activeCapabilities: capabilities })
  },

  switchWorkspace: (id: string, capabilities: string[] = []) => {
    localStorage.setItem(STORAGE_WORKSPACE_ID, id)
    set({ activeWorkspaceId: id, activeCapabilities: capabilities })
  },

  clearActiveWorkspaceId: () => {
    localStorage.removeItem(STORAGE_WORKSPACE_ID)
    set({ activeWorkspaceId: null, activeCapabilities: [] })
  },
}))

export function getActiveWorkspaceId(): string | null {
  return useWorkspaceStore.getState().activeWorkspaceId
}

export function hasWorkspaceCapability(capability: string): boolean {
  return useWorkspaceStore.getState().activeCapabilities.includes(capability)
}
