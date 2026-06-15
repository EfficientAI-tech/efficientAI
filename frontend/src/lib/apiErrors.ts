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

  if (typeof detail === 'object' && detail !== null && 'message' in detail) {
    const message = String((detail as { message: unknown }).message)
    if (message.trim()) return message
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

/** Like getApiErrorMessage, but parses JSON error bodies returned as Blob (e.g. responseType: 'blob'). */
export async function getBlobApiErrorMessage(
  error: unknown,
  fallback: string,
): Promise<string> {
  const err = error as { response?: { data?: unknown } }
  const data = err?.response?.data

  if (data && typeof data === 'object' && !(data instanceof Blob)) {
    return getApiErrorMessage(error, fallback)
  }

  const text = await readResponseBodyText(data)
  if (text) {
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
        return parsed.detail
      }
      if (
        typeof parsed.detail === 'object' &&
        parsed.detail !== null &&
        'message' in parsed.detail
      ) {
        const message = String((parsed.detail as { message: unknown }).message)
        if (message.trim()) return message
      }
    } catch {
      if (text.trim()) return text.trim()
    }
  }

  return getApiErrorMessage(error, fallback)
}

async function readResponseBodyText(data: unknown): Promise<string | null> {
  if (data instanceof Blob) {
    return data.text()
  }
  if (typeof data === 'string') {
    return data
  }
  if (data instanceof ArrayBuffer) {
    return new TextDecoder().decode(data)
  }
  if (
    typeof data === 'object' &&
    data !== null &&
    'text' in data &&
    typeof (data as { text: () => Promise<string> }).text === 'function'
  ) {
    return (data as { text: () => Promise<string> }).text()
  }
  return null
}
