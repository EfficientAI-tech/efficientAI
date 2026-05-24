import { create } from 'zustand'

/**
 * Workspace store for the EfficientAI frontend.
 *
 * A workspace is the in-org isolation boundary for call imports and metrics
 * (see migration 033 / app/api/v1/routes/workspaces.py). The active
 * workspace id is sent on every API call as `X-Workspace-Id`; switching
 * workspace + invalidating react-query caches is what scopes the UI to
 * a different project's data.
 *
 * The store is intentionally thin - membership management and the workspace
 * list itself live in react-query (`['workspaces']`). We only persist:
 *   - the currently selected workspace id (per-tab via localStorage), so a
 *     reload doesn't bounce the user back to "Default".
 */

const STORAGE_WORKSPACE_ID = 'activeWorkspaceId'

interface WorkspaceState {
  activeWorkspaceId: string | null
  setActiveWorkspaceId: (id: string | null) => void
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

  setActiveWorkspaceId: (id: string | null) => {
    if (id) {
      localStorage.setItem(STORAGE_WORKSPACE_ID, id)
    } else {
      localStorage.removeItem(STORAGE_WORKSPACE_ID)
    }
    set({ activeWorkspaceId: id })
  },

  clearActiveWorkspaceId: () => {
    localStorage.removeItem(STORAGE_WORKSPACE_ID)
    set({ activeWorkspaceId: null })
  },
}))

/**
 * Read the currently-selected workspace id without subscribing to the
 * store. The axios request interceptor uses this so it doesn't have to
 * hook into React state.
 */
export function getActiveWorkspaceId(): string | null {
  return useWorkspaceStore.getState().activeWorkspaceId
}
