/** Strip stack traces / provider dumps from diarisation row errors for UI. */
export function formatDiarisationError(message: string | null | undefined): string {
  if (!message) return ''
  let text = message.trim()
  for (const sep of ['\nDetails:', '\nTraceback (most recent call last):']) {
    const idx = text.indexOf(sep)
    if (idx >= 0) text = text.slice(0, idx).trim()
  }
  if (text.includes('does not accept audio input via Chat Completions')) {
    const providerIdx = text.indexOf('Provider error:')
    if (providerIdx >= 0) text = text.slice(0, providerIdx).trim()
  }
  return text.replace(/\s+/g, ' ')
}
