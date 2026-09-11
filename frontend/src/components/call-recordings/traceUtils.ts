export type ComponentKind = 'stt' | 'llm' | 'tts' | 's2s'
export type PipelineMode = 's2s' | 'stt_llm_tts'

export interface TraceTurnLike {
  turn_number: number
  sut_response_latency_ms?: number | null
  talk_over?: boolean
  stt_ttfb_ms?: number | null
  llm_ttfb_ms?: number | null
  tts_ttfb_ms?: number | null
  s2s_ttfb_ms?: number | null
  caller_stream_complete_at?: number | null
  sut_speech_start_at?: number | null
  sut_speech_stop_at?: number | null
  extra?: {
    was_interrupted?: boolean
    pipeline_mode?: PipelineMode
    user_text?: string
    assistant_text?: string
    is_opener?: boolean
  }
}

export interface OtelSpanLike {
  trace_id: string
  span_id: string
  parent_span_id?: string | null
  name: string
  start_time_unix_nano?: number | null
  end_time_unix_nano?: number | null
  attributes?: Record<string, unknown>
  events?: Array<{ name?: string; attributes?: Record<string, unknown> }>
}

export const FAILURE_FLAG_LABELS: Record<string, string> = {
  no_turns: 'No turns',
  high_latency: 'High latency',
}

export const PIPELINE_MODE_LABELS: Record<PipelineMode, string> = {
  s2s: 'S2S',
  stt_llm_tts: 'STT · LLM · TTS',
}

export function formatMs(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${Math.round(value)}ms`
}

export function formatCallDuration(startedAt?: string | null, endedAt?: string | null): string | null {
  if (!startedAt || !endedAt) return null
  const ms = new Date(endedAt).getTime() - new Date(startedAt).getTime()
  if (ms < 0) return null
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}m ${s}s`
}

export function sessionPipelineMode(turns: TraceTurnLike[]): PipelineMode | null {
  if (turns.some((t) => t.extra?.pipeline_mode === 's2s' || (t.s2s_ttfb_ms != null && t.s2s_ttfb_ms > 0))) {
    return 's2s'
  }
  if (turns.some((t) => t.stt_ttfb_ms || t.llm_ttfb_ms || t.tts_ttfb_ms)) return 'stt_llm_tts'
  return null
}

export function isTurnIncomplete(turn: TraceTurnLike, mode: PipelineMode | null): boolean {
  const extra = turn.extra ?? {}
  if (extra.is_opener || (extra.assistant_text && !extra.user_text)) {
    return false
  }

  const hasData =
    turn.sut_response_latency_ms != null ||
    turn.stt_ttfb_ms != null ||
    turn.llm_ttfb_ms != null ||
    turn.tts_ttfb_ms != null ||
    turn.s2s_ttfb_ms != null
  if (!hasData) return false

  if (mode === 's2s') {
    return turn.sut_response_latency_ms != null && (turn.s2s_ttfb_ms == null || turn.s2s_ttfb_ms <= 0)
  }
  if (turn.sut_response_latency_ms == null) return false
  const missingLlm = turn.llm_ttfb_ms == null || turn.llm_ttfb_ms <= 0
  const missingStages =
    (turn.stt_ttfb_ms == null || turn.stt_ttfb_ms <= 0) &&
    (turn.tts_ttfb_ms == null || turn.tts_ttfb_ms <= 0)
  return missingLlm || missingStages
}

export function spanHasError(span: OtelSpanLike): boolean {
  const attrs = span.attributes ?? {}
  const status = String(attrs['otel.status_code'] ?? attrs['status'] ?? '').toUpperCase()
  if (status === 'ERROR') return true
  if (attrs['error'] === true) return true
  if (attrs['exception.type'] || attrs['exception.message']) return true
  return (span.events ?? []).some((e) => {
    const n = String(e.name ?? '').toLowerCase()
    return n.includes('exception') || n.includes('error')
  })
}
