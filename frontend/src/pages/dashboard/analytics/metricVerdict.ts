import { MIN_SAMPLE_SIZE, type Polarity } from './metricMath'

export type VerdictKind = 'relevant' | 'redundant' | 'needs_data'

export interface MetricVerdict {
  kind: VerdictKind
  reasons: string[]
  twinName?: string
}

export interface VerdictInput {
  values: number[]
  perAgentMeans: Record<string, { name: string; mean: number; count: number }>
  perScenarioMeans?: Record<string, { name: string; mean: number; count: number }>
  otherMetrics?: Array<{ id: string; name: string; values: number[] }>
  polarity?: Polarity
}

function mean(values: number[]): number {
  if (values.length === 0) return 0
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function variance(values: number[]): number {
  if (values.length < 2) return 0
  const avg = mean(values)
  return values.reduce((sum, value) => sum + (value - avg) ** 2, 0) / values.length
}

function pearson(a: number[], b: number[]): number | null {
  const n = Math.min(a.length, b.length)
  if (n < MIN_SAMPLE_SIZE) return null
  const left = a.slice(0, n)
  const right = b.slice(0, n)
  const meanA = mean(left)
  const meanB = mean(right)
  let num = 0
  let denA = 0
  let denB = 0
  for (let i = 0; i < n; i += 1) {
    const da = left[i] - meanA
    const db = right[i] - meanB
    num += da * db
    denA += da * da
    denB += db * db
  }
  if (denA === 0 || denB === 0) return denA === 0 && denB === 0 ? 1 : null
  return num / Math.sqrt(denA * denB)
}

export function verdictForMetric(input: VerdictInput): MetricVerdict {
  const n = input.values.length
  if (n < MIN_SAMPLE_SIZE) {
    return {
      kind: 'needs_data',
      reasons: [`Only ${n} scored call${n === 1 ? '' : 's'} — need at least ${MIN_SAMPLE_SIZE} before this metric can be trusted.`],
    }
  }

  for (const other of input.otherMetrics ?? []) {
    const aligned = Math.min(input.values.length, other.values.length)
    if (aligned < MIN_SAMPLE_SIZE) continue
    const agreement = pearson(input.values, other.values)
    if (agreement != null && agreement >= 0.9) {
      return {
        kind: 'redundant',
        twinName: other.name,
        reasons: [
          `Moves in lockstep with ${other.name} (r=${agreement.toFixed(2)}). One of the two is enough.`,
        ],
      }
    }
  }

  const agentMeans = Object.values(input.perAgentMeans)
    .filter((item) => item.count >= 2)
    .map((item) => item.mean)
  const scenarioMeans = Object.values(input.perScenarioMeans ?? {})
    .filter((item) => item.count >= 2)
    .map((item) => item.mean)
  const agentVar = variance(agentMeans)
  const periodVar = variance(input.values)
  const scenarioVar = variance(scenarioMeans)

  if (agentVar < 0.002 && periodVar < 0.002 && (scenarioMeans.length === 0 || scenarioVar < 0.002)) {
    const sample = input.values[0]
    return {
      kind: 'redundant',
      reasons: [
        `Nearly constant across agents and the selected window (≈${Number(sample.toFixed(2))}). It is not discriminating anything right now.`,
      ],
    }
  }

  const reasons: string[] = []
  const worseFirst = input.polarity === 'lower_is_better'
    ? (a: number, b: number) => b - a
    : (a: number, b: number) => a - b
  const rankedAgents = Object.values(input.perAgentMeans)
    .filter((item) => item.count >= 2)
    .sort((a, b) => worseFirst(a.mean, b.mean))
  if (rankedAgents.length >= 2 && agentVar >= 0.002) {
    reasons.push(
      `Separates agents: ${rankedAgents[0].name} is weakest, ${rankedAgents[rankedAgents.length - 1].name} is strongest.`,
    )
  }
  const rankedScenarios = Object.values(input.perScenarioMeans ?? {})
    .filter((item) => item.count >= 2)
    .sort((a, b) => worseFirst(a.mean, b.mean))
  if (rankedScenarios.length >= 2 && scenarioVar >= 0.002) {
    reasons.push(`Biggest scenario gap is ${rankedScenarios[0].name}.`)
  }
  if (periodVar >= 0.002) {
    reasons.push('The score is moving over time, so it is worth watching.')
  }
  if (reasons.length === 0) {
    reasons.push('Scores vary enough across calls to keep this metric in the suite.')
  }
  return { kind: 'relevant', reasons }
}
