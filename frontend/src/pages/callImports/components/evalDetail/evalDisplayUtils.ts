export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

export function formatRecordingDate(value: string | null | undefined): string {
  if (!value) return '-'
  const [year, month, day] = value.split('-')
  return year && month && day ? `${day}/${month}/${year}` : value
}

export function formatPct(ratio: number): string {
  if (!Number.isFinite(ratio)) return '—'
  return `${Math.round(ratio * 100)}%`
}

export function clampProseToSentences(
  text: string,
  maxSentences = 3,
  maxChars = 300,
): string {
  const trimmed = text.trim().replace(/\s*\n+\s*/g, ' ')
  if (!trimmed) return trimmed
  const sentences = trimmed.split(/(?<=[.!?])\s+/).filter(Boolean)
  let result = (sentences.length ? sentences.slice(0, maxSentences) : [trimmed])
    .join(' ')
    .trim()
  if (result.length > maxChars) {
    const cut = result.slice(0, maxChars - 3).replace(/\s+\S*$/, '')
    result = `${cut || result.slice(0, maxChars)}...`
  }
  return result
}

export const PROVIDER_DISPLAY: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  deepseek: 'DeepSeek',
  groq: 'Groq',
}
