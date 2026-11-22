import { create } from 'zustand'

/** Lets any page open the assistant, optionally sending a first message. */
type CopilotState = {
  open: boolean
  pendingPrompt: string | null
  setOpen: (open: boolean) => void
  openWith: (prompt: string) => void
  takePendingPrompt: () => string | null
}

export const useCopilotStore = create<CopilotState>((set, get) => ({
  open: false,
  pendingPrompt: null,
  setOpen: (open) => set({ open }),
  openWith: (prompt) => set({ open: true, pendingPrompt: prompt }),
  takePendingPrompt: () => {
    const prompt = get().pendingPrompt
    if (prompt) set({ pendingPrompt: null })
    return prompt
  },
}))

export type CreateAgentPrefill = {
  name?: string
  call_medium?: 'voice' | 'chat'
  production_prompt?: string | null
  description?: string | null
}
