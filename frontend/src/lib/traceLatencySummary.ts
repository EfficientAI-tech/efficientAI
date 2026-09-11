export type TraceTurnLatencyInput = {
  sut_response_latency_ms?: number | null
  s2s_ttfb_ms?: number | null
  llm_ttfb_ms?: number | null
  extra?: {
    user_text?: string | null
    assistant_text?: string | null
    sut_measured_e2e?: boolean | null
    sut_is_partial_fallback?: boolean | null
  } | null
}

export function isEligibleResponseLatencySample(turn: TraceTurnLatencyInput): boolean {
  const sut = turn.sut_response_latency_ms
  if (sut == null) return false
  const extra = turn.extra ?? {}
  if (extra.user_text) {
    return !extra.sut_is_partial_fallback
  }
  if (extra.sut_measured_e2e) return true
  if (!extra.assistant_text) return false
  if (turn.s2s_ttfb_ms != null) return true
  const llm = turn.llm_ttfb_ms
  if (llm == null) return true
  return Math.abs(sut - llm) > 1
}

export function responseLatencySampleLabel(sampleCount: number, totalTurns: number): string | undefined {
  if (sampleCount <= 0) return undefined
  if (sampleCount < totalTurns) return `${sampleCount} of ${totalTurns} turns`
  return `${sampleCount} turns`
}

export const RESPONSE_LATENCY_SAMPLE_HINT =
  'Uses turns where the user spoke and the agent replied. Agent-only greetings are not included.'

export function responseLatencySamples(turns: TraceTurnLatencyInput[]): number[] {
  const values: number[] = []
  for (const turn of turns) {
    if (!isEligibleResponseLatencySample(turn)) continue
    values.push(turn.sut_response_latency_ms as number)
  }
  return values
}

function roundHalfToEven(value: number): number {
  const floor = Math.floor(value)
  const frac = value - floor
  if (frac !== 0.5) return Math.round(value)
  return floor % 2 === 0 ? floor : floor + 1
}

export function latencyPercentile(values: number[], pct: number): number | null {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const idx = Math.min(
    sorted.length - 1,
    roundHalfToEven((pct / 100) * (sorted.length - 1)),
  )
  return Math.round(sorted[idx] * 10) / 10
}

export function computeResponseLatencySummary(turns: TraceTurnLatencyInput[]) {
  let values = responseLatencySamples(turns)
  if (!values.length) {
    values = turns
      .map((turn) => turn.s2s_ttfb_ms)
      .filter((value): value is number => value != null)
  }
  if (!values.length) {
    values = turns
      .map((turn) => turn.llm_ttfb_ms)
      .filter((value): value is number => value != null)
  }
  if (!values.length) return null
  return {
    sampleCount: values.length,
    p50: latencyPercentile(values, 50),
    p90: latencyPercentile(values, 90),
    p95: latencyPercentile(values, 95),
  }
}
