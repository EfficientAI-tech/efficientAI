export const STAGE_COLORS = {
  stt: '#60a5fa',
  llm: '#fde047',
  tts: '#2dd4bf',
  s2s: '#c084fc',
  transport: '#fb923c',
  endpointing: '#4ade80',
  analysis: '#a78bfa',
} as const

export const CHART_BAR = {
  default: '#e5e7eb',
  peak: '#fde047',
} as const

export const WAVEFORM_COLORS = {
  user: '#fb923c',
  assistant: '#2dd4bf',
  mono: '#c4b5fd',
  playhead: '#eab308',
  canvasBg: '#f9fafb',
  skeleton: 'rgba(148, 163, 184, 0.28)',
} as const

export const METRIC_COST_COLORS: Record<string, string> = {
  transport: STAGE_COLORS.transport,
  stt: STAGE_COLORS.stt,
  llm: '#eab308',
  tts: STAGE_COLORS.tts,
  vapi: '#f87171',
  analysis: STAGE_COLORS.analysis,
  knowledge: '#818cf8',
  other: '#94a3b8',
}
