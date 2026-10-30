export const INSIGHT_BLUE = '#3b82f6'
export const INSIGHT_BLUE_FILL = '#93c5fd'
export const INSIGHT_BLUE_SOFT = '#dbeafe'

export function percentDelta(current: number, previous: number): number | null {
  if (previous === 0) return current === 0 ? 0 : 100
  return ((current - previous) / Math.abs(previous)) * 100
}

export function formatDelta(delta: number | null): { text: string; up: boolean } | null {
  if (delta == null || Number.isNaN(delta)) return null
  const up = delta >= 0
  return {
    up,
    text: `${up ? 'Up' : 'Down'} ${Math.abs(delta).toFixed(2)}% from previous period`,
  }
}
