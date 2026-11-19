/** Keeps Evaluation Results hub filters (dates, tab, scope) while drilling into a run. */

function storageKey(workspaceId: string | null | undefined) {
  return workspaceId
    ? `evaluator-results-hub-search:${workspaceId}`
    : 'evaluator-results-hub-search'
}

const HUB_SCOPE_KEYS = [
  'start',
  'end',
  'dates',
  'tab',
  'agent',
  'suite',
  'scenario',
  'run_source',
  'status',
] as const

export function persistResultsHubQueryString(queryString: string, workspaceId?: string | null) {
  const trimmed = queryString.trim()
  if (!trimmed) return
  try {
    sessionStorage.setItem(storageKey(workspaceId), trimmed)
  } catch {
    /* ignore quota / private mode */
  }
}

export function readPersistedResultsHubQueryString(workspaceId?: string | null): string {
  try {
    if (!workspaceId) return sessionStorage.getItem('evaluator-results-hub-search') ?? ''
    return sessionStorage.getItem(storageKey(workspaceId)) ?? ''
  } catch {
    return ''
  }
}

export function clearResultsHubQueryString(workspaceId?: string | null) {
  try {
    if (workspaceId) sessionStorage.removeItem(storageKey(workspaceId))
    sessionStorage.removeItem('evaluator-results-hub-search')
  } catch {
    /* ignore */
  }
}

export function resultsHubHref(queryString = '', workspaceId?: string | null): string {
  const qs = queryString || readPersistedResultsHubQueryString(workspaceId)
  return qs ? `/results?${qs}` : '/results'
}

export function resultsDetailHref(resultId: string, hubQueryString: string): string {
  const hubPath = hubQueryString ? `/results?${hubQueryString}` : resultsHubHref()
  return `/results/${resultId}?from=${encodeURIComponent(hubPath)}`
}

export function resolveResultsHubBackPath(fromSearchParam: string | null, workspaceId?: string | null): string {
  if (fromSearchParam) {
    try {
      const decoded = decodeURIComponent(fromSearchParam)
      if (decoded.startsWith('/results')) return decoded
    } catch {
      /* ignore malformed */
    }
  }
  return resultsHubHref('', workspaceId)
}

export function resultsHubHrefWithScope(
  hubPath: string,
  scope: { agentId?: string | null; suiteId?: string | null; scenarioId?: string | null },
): string {
  const qIndex = hubPath.indexOf('?')
  const path = qIndex >= 0 ? hubPath.slice(0, qIndex) : hubPath
  const params = new URLSearchParams(qIndex >= 0 ? hubPath.slice(qIndex + 1) : readPersistedResultsHubQueryString())
  if (scope.agentId) params.set('agent', scope.agentId)
  else params.delete('agent')
  if (scope.suiteId) params.set('suite', scope.suiteId)
  else params.delete('suite')
  if (scope.scenarioId) params.set('scenario', scope.scenarioId)
  else params.delete('scenario')
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

export function hubSearchHasDateScope(params: URLSearchParams): boolean {
  return params.get('dates') === 'all' || Boolean(params.get('start') && params.get('end'))
}

export function mergePersistedHubScope(current: URLSearchParams, saved: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(current)
  for (const key of HUB_SCOPE_KEYS) {
    const value = saved.get(key)
    if (value != null && value !== '') next.set(key, value)
  }
  return next
}