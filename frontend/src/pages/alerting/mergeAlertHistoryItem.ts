export type AlertHistoryLike = {
  id: string
  status: string
  alert?: unknown
  notification_details?: Record<string, unknown> | null
}

export function normalizeHistoryStatus(status: unknown): string {
  if (typeof status === 'string') return status.toLowerCase()
  if (status && typeof status === 'object' && 'value' in status) {
    return String((status as { value: string }).value).toLowerCase()
  }
  return String(status ?? '').toLowerCase()
}

/** Merge API update into UI state without dropping nested alert or stale-empty notification_details. */
export function mergeAlertHistoryItem<T extends AlertHistoryLike>(
  previous: T,
  updated: Partial<T> & { id: string }
): T {
  const nextDetails = updated.notification_details
  const prevDetails = previous.notification_details
  let notification_details = prevDetails
  if (nextDetails != null) {
    notification_details =
      Object.keys(nextDetails).length > 0 ? nextDetails : prevDetails
  }

  return {
    ...previous,
    ...updated,
    status: normalizeHistoryStatus(updated.status ?? previous.status),
    alert: updated.alert !== undefined ? updated.alert : previous.alert,
    notification_details,
  }
}
