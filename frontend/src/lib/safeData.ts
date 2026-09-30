/** Runtime-safe reads for API list payloads (avoid white-screen on partial/null responses). */

export function asArray<T>(value: unknown): T[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is T => item != null)
}

export function itemsOf<T = unknown>(data: unknown): T[] {
  if (Array.isArray(data)) return asArray<T>(data)
  if (data == null || typeof data !== 'object') return []
  return asArray<T>((data as { items?: unknown }).items)
}

export function safeString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

export function shortId(value: unknown, length = 8): string {
  const s = safeString(value)
  if (!s) return '—'
  return s.length > length ? s.slice(0, length) : s
}
