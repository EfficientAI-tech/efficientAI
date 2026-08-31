/** Keys stored in ``metric_scores`` that are not real Metric IDs. */
const RESERVED_METRIC_SCORE_KEYS = new Set(['_billing', '__discovered_metrics__'])

export function isReservedMetricScoreKey(key: string): boolean {
  if (!key) return true
  if (RESERVED_METRIC_SCORE_KEYS.has(key)) return true
  if (key.endsWith('__discovered')) return true
  return false
}

export function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          const msg = String((item as { msg?: unknown }).msg ?? '')
          const loc = (item as { loc?: unknown }).loc
          if (Array.isArray(loc) && loc.length > 0) {
            return `${loc.join('.')}: ${msg}`
          }
          return msg
        }
        return typeof item === 'string' ? item : null
      })
      .filter((part): part is string => !!part && part.trim().length > 0)
    if (parts.length > 0) return parts.join('; ')
  }
  if (detail && typeof detail === 'object' && 'msg' in detail) {
    return String((detail as { msg?: unknown }).msg ?? fallback)
  }
  return fallback
}
