/** Extract a user-facing message from a failed API client response. */
export function getApiErrorMessage(error: unknown, fallback: string): string {
  const err = error as {
    response?: { data?: { detail?: unknown } }
    message?: string
  }
  const detail = err?.response?.data?.detail

  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }

  if (Array.isArray(detail)) {
    const message = detail
      .map((item) => {
        if (typeof item === 'object' && item !== null && 'msg' in item) {
          return String((item as { msg: string }).msg)
        }
        return String(item)
      })
      .filter(Boolean)
      .join(', ')
    if (message) return message
  }

  if (typeof err?.message === 'string' && err.message.trim()) {
    return err.message
  }

  return fallback
}
