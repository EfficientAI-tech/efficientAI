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

function coerceToErrorText(raw: unknown): string {
  if (raw == null) return ''
  if (typeof raw === 'string') return raw
  if (typeof raw === 'object' && raw !== null && 'message' in raw) {
    return String((raw as { message: unknown }).message)
  }
  return String(raw)
}

function stripPythonTraceback(text: string): string {
  let result = text
  for (const marker of [
    '\nTraceback (most recent call last):',
    '\nDuring handling of the above exception',
  ]) {
    const idx = result.indexOf(marker)
    if (idx >= 0) {
      result = result.slice(0, idx)
    }
  }
  return result.trim()
}

function pickBestErrorLine(lines: string[]): string | null {
  if (!lines.length) return null
  const preferred = lines.find(
    (line) =>
      /does not exist|not found|invalid|failed|error|exception|unauthorized|rate limit/i.test(
        line,
      ) &&
      !line.startsWith('File ') &&
      !line.includes('site-packages'),
  )
  return preferred || lines[0]
}

/** Turn a long LLM/stack-trace failure into a short label plus optional detail text. */
export function summarizeFlowchartError(raw: unknown): {
  summary: string
  details: string | null
} {
  const text = coerceToErrorText(raw).trim()
  if (!text) {
    return { summary: 'Flowchart generation failed.', details: null }
  }

  const withoutTrace = stripPythonTraceback(text)
  const lines = withoutTrace
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  let summary = pickBestErrorLine(lines) || 'Flowchart generation failed.'
  if (summary.length > 320) {
    summary = `${summary.slice(0, 317)}…`
  }

  const hadTraceback = text.length > withoutTrace.length + 10
  const details =
    hadTraceback || withoutTrace.length > summary.length + 24
      ? withoutTrace
      : null

  return { summary, details: details && details !== summary ? details : null }
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
