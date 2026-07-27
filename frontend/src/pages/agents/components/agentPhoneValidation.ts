import type { AgentPhoneAssignmentConflict } from '../../../types/api'

export function formatAgentPhoneConflictMessage(conflict: AgentPhoneAssignmentConflict): string {
  return `This number is already assigned to agent "${conflict.agent_name}".`
}

export function extractPhoneConflictDetail(detail: unknown): string | null {
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) {
      return message
    }
  }
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  return null
}
