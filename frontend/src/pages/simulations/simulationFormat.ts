import type { SimulationRunStatus } from '../../types/api'

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

export function formatDuration(start?: string | null, end?: string | null): string {
  if (!start) return '—'
  const ms = (end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime()
  const totalSeconds = Math.max(0, Math.round(ms / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`
}

// Sequential single-hue (blue) ramp for reward magnitude: light = low, dark = high.
const REWARD_RAMP = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95']

export function rewardCellStyle(reward?: number | null): { background: string; color: string } {
  if (reward === null || reward === undefined) return { background: '#f3f4f6', color: '#6b7280' }
  const idx = Math.min(REWARD_RAMP.length - 1, Math.floor(reward * REWARD_RAMP.length))
  return { background: REWARD_RAMP[idx], color: idx >= 3 ? '#ffffff' : '#111827' }
}

export const REWARD_BAR_COLOR = '#2a78d6'
