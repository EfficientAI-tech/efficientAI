import type {
  EventStatus,
  EventType,
  IssueCategory,
  IssueSeverity,
  IssueSource,
  SessionKind,
  SessionStatus,
} from './types'

export const ISSUE_CATEGORY_LABELS: Record<IssueCategory, string> = {
  tool_failed: 'Tool call failed',
  invalid_tool_args: 'Invalid tool arguments',
  wrong_tool: 'Wrong or unavailable tool',
  skill_misuse: 'Skill misuse',
  external_api_failure: 'External API failure',
  retrieval_problem: 'Retrieval problem',
  harness_llm_error: 'Harness / LLM error',
  policy_violation: 'Policy violation',
  expected_action_missing: 'Expected action missing',
  user_flagged: 'User flagged',
}

export const DEFAULT_SEVERITY: Record<IssueCategory, IssueSeverity> = {
  tool_failed: 'error',
  invalid_tool_args: 'error',
  wrong_tool: 'error',
  skill_misuse: 'warning',
  external_api_failure: 'error',
  retrieval_problem: 'warning',
  harness_llm_error: 'error',
  policy_violation: 'warning',
  expected_action_missing: 'error',
  user_flagged: 'warning',
}

export const SEVERITY_LABELS: Record<IssueSeverity, string> = {
  error: 'Error',
  warning: 'Warning',
  info: 'Info',
}

export const SOURCE_LABELS: Record<IssueSource, string> = {
  rule: 'Rule-based',
  llm_judge: 'LLM judge',
  user: 'User flagged',
}

export const EVENT_TYPE_LABELS: Record<EventType, string> = {
  llm: 'LLM',
  tool: 'Tool',
  skill: 'Skill',
  api: 'API',
  rag: 'RAG',
  db: 'DB',
  harness: 'Harness',
  message: 'Message',
}

export const STATUS_LABELS: Record<SessionStatus, string> = {
  draft: 'Draft',
  queued: 'Queued',
  running: 'Running',
  evaluating: 'Evaluating',
  completed: 'Completed',
  failed: 'Failed',
  stopped: 'Stopped',
  active: 'Active',
  idle: 'Idle',
  ended: 'Ended',
}

export function sessionKindLabel(kind: SessionKind): string {
  return kind === 'simulation' ? 'Simulation' : 'Manual'
}

export function eventStatusLabel(status: EventStatus): string {
  if (status === 'ok') return 'OK'
  if (status === 'timeout') return 'Timeout'
  return 'Error'
}

export function isInProgressStatus(status: SessionStatus): boolean {
  return status === 'queued' || status === 'running' || status === 'evaluating' || status === 'active'
}

export function formatDuration(seconds?: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  if (mins <= 0) return `${secs}s`
  return `${mins}m ${secs}s`
}
