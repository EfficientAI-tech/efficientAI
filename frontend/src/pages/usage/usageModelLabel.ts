export type UsageModelLabelContext = {
  total_tokens?: number
  audio_seconds?: number
  tts_characters?: number
  call_count?: number
  usage_kind?: string | null
}

const KIND_LABELS: Record<string, string> = {
  llm: 'LLM',
  stt: 'STT',
  tts: 'TTS',
}

function unknownKindLabel(kind: string): string {
  const short = KIND_LABELS[kind]
  return short ? `${short} (unknown)` : 'Voice (unknown)'
}

function titleCaseSlug(value: string): string {
  return value
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ')
}

function formatKnownModel(model: string): string {
  const trimmed = model.trim()
  const lower = trimmed.toLowerCase()
  if (lower === 'voice-call') return 'Voice call'
  if (lower.endsWith('-stt')) {
    return `${titleCaseSlug(trimmed.slice(0, -4))} STT`
  }
  if (lower.endsWith('-tts')) {
    return `${titleCaseSlug(trimmed.slice(0, -4))} TTS`
  }
  return trimmed
}

function inferKindFromContext(context?: UsageModelLabelContext): string | null {
  if (!context) return null
  const kind = context.usage_kind
  if (kind === 'llm' || kind === 'stt' || kind === 'tts') return kind

  const tokens = context.total_tokens ?? 0
  const audio = context.audio_seconds ?? 0
  const tts = context.tts_characters ?? 0
  const active = [
    tokens > 0 ? 'llm' : null,
    audio > 0 ? 'stt' : null,
    tts > 0 ? 'tts' : null,
  ].filter(Boolean) as string[]
  if (active.length === 1) return active[0]
  return null
}

export function usageModelDisplayLabel(
  model: string | null | undefined,
  context?: UsageModelLabelContext,
): string {
  if (!model?.trim()) return '—'
  const trimmed = model.trim()
  if (trimmed.toLowerCase() !== 'unknown') {
    return formatKnownModel(trimmed)
  }

  const kind = inferKindFromContext(context)
  if (kind) return unknownKindLabel(kind)
  return 'Voice (unknown)'
}
