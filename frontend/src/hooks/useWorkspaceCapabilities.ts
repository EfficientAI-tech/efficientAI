import { useMemo } from 'react'
import { useWorkspaceStore } from '../store/workspaceStore'

/** Hook for cosmetic UI gating based on active workspace capabilities. */
export function useWorkspaceCapabilities() {
  const capabilities = useWorkspaceStore((s) => s.activeCapabilities)

  return useMemo(
    () => ({
      capabilities,
      has: (cap: string) => capabilities.includes(cap),
      canViewMembers: capabilities.includes('workspace.members.view'),
      canManageMembers: capabilities.includes('workspace.members.manage'),
      canImportCalls: capabilities.includes('calls.import'),
      canManageMetrics: capabilities.includes('metrics.manage'),
      canRunEvals: capabilities.includes('evals.run'),
    }),
    [capabilities],
  )
}
