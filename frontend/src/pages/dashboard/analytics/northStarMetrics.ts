import type { ScoredMetric } from './types'

const STORAGE_KEY = 'dashboardNorthStar.v1'

type NorthStarMap = Record<string, string[]>

function readMap(): NorthStarMap {
  if (typeof window === 'undefined') return {}
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    return parsed as NorthStarMap
  } catch {
    return {}
  }
}

function writeMap(map: NorthStarMap) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(map))
}

export function getPinnedMetricIds(agentId: string): string[] {
  return readMap()[agentId] ?? []
}

export function setPinnedMetricIds(agentId: string, metricIds: string[]): string[] {
  const nextIds = metricIds.slice(0, 3)
  const map = readMap()
  map[agentId] = nextIds
  writeMap(map)
  return nextIds
}

export function togglePinnedMetric(agentId: string, metricId: string, fallbackIds: string[]): string[] {
  const current = getPinnedMetricIds(agentId)
  const base = current.length > 0 ? current : fallbackIds
  const next = base.includes(metricId)
    ? base.filter((id) => id !== metricId)
    : [...base, metricId].slice(-3)
  return setPinnedMetricIds(agentId, next)
}

export function defaultNorthStarIds(metrics: ScoredMetric[]): string[] {
  return [...metrics]
    .filter((metric) => metric.agg.metric_category !== 'user_insight')
    .sort((a, b) => b.score.count - a.score.count)
    .slice(0, 3)
    .map((metric) => metric.agg.metric_id)
}
