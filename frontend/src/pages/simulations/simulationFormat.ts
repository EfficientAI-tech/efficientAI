import type { SimulationRun, SimulationRunStatus } from '../../types/api'

export const ACTIVE_RUN_STATUSES: SimulationRunStatus[] = ['queued', 'preparing', 'running', 'ingesting']

export function isRunActive(status: SimulationRunStatus): boolean {
  return ACTIVE_RUN_STATUSES.includes(status)
}

export function formatPct(value?: number | null): string {
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`
}

export function formatScore(value?: number | null): string {
  return value === null || value === undefined ? '—' : value.toFixed(2)
}

export function formatLlmPair(provider?: string | null, model?: string | null): string | null {
  const name = model?.trim()
  if (!name) return null
  const who = provider?.trim()
  return who ? `${who}/${name}` : name
}

/** Model label for one side of a run; older runs only stored overrides. */
export function runLlmLabel(
  run: SimulationRun,
  side: 'production' | 'test',
  fallback?: { provider?: string | null; model?: string | null },
): string {
  const resolved = run.resolved_llms?.[side]
  if (resolved?.label) return resolved.label
  const [provider, model] =
    side === 'production'
      ? [run.production_llm_provider, run.production_llm_model]
      : [run.test_llm_provider, run.test_llm_model]
  return formatLlmPair(provider, model) || formatLlmPair(fallback?.provider, fallback?.model) || 'Not recorded'
}

export function formatDuration(start?: string | null, end?: string | null): string {
  if (!start) return '—'
  const ms = (end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime()
  const totalSeconds = Math.max(0, Math.round(ms / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`
}

// Sequential ramp in the platform's yellow (tailwind primary-100 → primary-800):
// light yellow = low reward, dark yellow = high. Text flips to white on the two
// darkest steps, where white keeps ≥4.5:1 contrast.
const REWARD_RAMP = ['#fef9c3', '#fef08a', '#fde047', '#eab308', '#a16207', '#854d0e']

export function rewardCellStyle(reward?: number | null): { background: string; color: string } {
  if (reward === null || reward === undefined) return { background: '#f3f4f6', color: '#6b7280' }
  const idx = Math.min(REWARD_RAMP.length - 1, Math.floor(reward * REWARD_RAMP.length))
  return { background: REWARD_RAMP[idx], color: idx >= 4 ? '#ffffff' : '#111827' }
}

// primary-600, the platform's dark yellow.
export const REWARD_BAR_COLOR = '#ca8a04'
