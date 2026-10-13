import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type PlatformImportWatch = {
  id: string
  label: string
  pinnedAt: number
}

type State = {
  watches: PlatformImportWatch[]
  panelOpen: boolean
  panelMinimized: boolean
  pin: (id: string, label: string) => void
  unpin: (id: string) => void
  setPanelOpen: (open: boolean) => void
  setPanelMinimized: (minimized: boolean) => void
  openPanel: () => void
}

export const usePlatformImportProgressStore = create<State>()(
  persist(
    (set, get) => ({
      watches: [],
      panelOpen: false,
      panelMinimized: false,
      pin: (id, label) => {
        const existing = get().watches.find((w) => w.id === id)
        if (existing) {
          if (existing.label !== label) {
            set({
              watches: get().watches.map((w) => (w.id === id ? { ...w, label } : w)),
            })
          }
          return
        }
        set({
          watches: [...get().watches, { id, label, pinnedAt: Date.now() }],
          panelOpen: true,
          panelMinimized: false,
        })
      },
      unpin: (id) => {
        set({ watches: get().watches.filter((w) => w.id !== id) })
      },
      setPanelOpen: (open) => set({ panelOpen: open }),
      setPanelMinimized: (minimized) => set({ panelMinimized: minimized }),
      openPanel: () => set({ panelOpen: true, panelMinimized: false }),
    }),
    {
      name: 'platform-import-progress',
      partialize: (state) => ({
        watches: state.watches,
        panelMinimized: state.panelMinimized,
      }),
    },
  ),
)
