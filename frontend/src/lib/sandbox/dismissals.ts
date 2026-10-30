import type { AgentDismissal, Issue } from './types'

export const DISMISSALS_STORAGE_KEY = 'eai.sandbox.agentDismissals'

export function issueSignature(issue: Pick<Issue, 'category' | 'configRef'>): string {
  const item = issue.configRef?.itemId || 'unknown'
  return `${issue.category}:${item}`
}

export function loadDismissals(): AgentDismissal[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(DISMISSALS_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function saveDismissals(items: AgentDismissal[]): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(DISMISSALS_STORAGE_KEY, JSON.stringify(items))
}

export function applyRememberedDismissals(
  issues: Issue[],
  dismissals: AgentDismissal[],
  agentId?: string,
): Issue[] {
  if (!issues.length) return issues
  const matching = dismissals.filter((d) => (agentId ? d.agentId === agentId : !d.agentId))
  if (!matching.length) return issues
  const bySignature = new Map(matching.map((d) => [d.signature, d]))
  return issues.map((issue) => {
    if (issue.status === 'dismissed') return issue
    const remembered = bySignature.get(issueSignature(issue))
    if (!remembered) return issue
    return {
      ...issue,
      status: 'dismissed',
      dismissReason: remembered.reason,
      dismissedAt: remembered.dismissedAt,
      rememberedFromSessionId: remembered.sourceSessionId,
    }
  })
}

export function upsertDismissal(
  existing: AgentDismissal[],
  next: AgentDismissal,
): AgentDismissal[] {
  const key = `${next.agentId ?? ''}::${next.signature}`
  const without = existing.filter((d) => `${d.agentId ?? ''}::${d.signature}` !== key)
  return [...without, next]
}

export function removeDismissal(
  existing: AgentDismissal[],
  signature: string,
  agentId?: string,
): AgentDismissal[] {
  return existing.filter((d) => !(d.signature === signature && (d.agentId ?? '') === (agentId ?? '')))
}
