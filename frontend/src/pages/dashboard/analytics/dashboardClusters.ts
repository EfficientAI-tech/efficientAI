import type { EvaluationMetricClustersState, MetricCluster } from '../../../types/api'
import { callFailed } from './callFailed'
import { globalMetricById } from './globalMetrics'
import type { MockCall } from './mockCalls'

export interface DashboardCluster {
  id: string
  label: string
  gapLabel: string | null
  count: number
  sharePct: number
  observation: string
  evidence: string | null
  suggestedPrompt: string
}

function fromCanned(cluster: MetricCluster, flagged: number): DashboardCluster {
  return {
    id: cluster.id,
    label: cluster.label,
    gapLabel: cluster.gap_label,
    count: cluster.count,
    sharePct: cluster.share_pct || (flagged ? Math.round((cluster.count / flagged) * 100) : 0),
    observation: cluster.observation,
    evidence: cluster.evidence?.quote ?? null,
    suggestedPrompt: promptFor(cluster.label, cluster.observation, cluster.gap_label),
  }
}

function promptFor(label: string, observation: string, gap?: string | null): string {
  const opener =
    gap === 'MISSING'
      ? 'Add a missing instruction:'
      : gap === 'LOGIC_GAP'
        ? 'Fix the logic:'
        : 'Be explicit:'
  return `${opener} when this happens (“${label}”), ${observation} Acknowledge first, then act.`
}

function deriveFromCalls(metricId: string, metricName: string, failing: MockCall[]): DashboardCluster[] {
  const total = failing.length
  if (total === 0) return []
  const buckets = new Map<string, { label: string; observation: string; evidence: string; count: number }>()
  const bump = (key: string, label: string, observation: string, evidence: string) => {
    const prev = buckets.get(key)
    if (prev) prev.count += 1
    else buckets.set(key, { label, observation, evidence, count: 1 })
  }

  for (const call of failing) {
    const score = call.metric_scores[metricId]
    if (call.endedEarly) {
      bump(
        `early:${call.endedReason ?? 'unknown'}`,
        `Ended early (${call.endedReason ?? 'unknown'})`,
        'The agent drops the caller before confirming an outcome or next step.',
        call.turns[call.turns.length - 1]?.text ?? '',
      )
    } else if (call.turns.some((turn) => turn.toolCall?.failed)) {
      const tool = call.turns.find((turn) => turn.toolCall?.failed)?.toolCall?.name ?? 'tool'
      bump(`tool:${tool}`, `${tool} failed`, `Retry or offer an alternative when ${tool} fails.`, tool)
    } else if (call.turns.some((turn) => turn.ragCall?.failed)) {
      bump('rag', 'RAG lookup failed', 'If policy search returns empty, say so and escalate instead of stalling.', 'policy lookup')
    } else if (score?.rationale) {
      bump(`rationale:${score.rationale.slice(0, 48)}`, score.rationale.slice(0, 72), score.rationale, score.rationale)
    } else if (call.scenarioName) {
      bump(
        `scenario:${call.scenarioId}`,
        call.scenarioName,
        `${metricName} fails most often on this scenario.`,
        call.turns[0]?.text ?? call.scenarioName,
      )
    } else {
      bump('other', `Other ${metricName} failures`, 'No concentrated pattern yet.', '')
    }
  }

  return [...buckets.values()]
    .sort((a, b) => b.count - a.count)
    .map((item, index) => ({
      id: `derived-${metricId}-${index}`,
      label: item.label,
      gapLabel: 'UNDERSPEC',
      count: item.count,
      sharePct: Math.round((item.count / total) * 100),
      observation: item.observation,
      evidence: item.evidence || null,
      suggestedPrompt: promptFor(item.label, item.observation, 'UNDERSPEC'),
    }))
}

export function clustersForMetric(
  metricId: string,
  metricName: string,
  calls: MockCall[],
  canned: EvaluationMetricClustersState | null | undefined,
): DashboardCluster[] {
  const failing = calls.filter((call) => callFailed(call, metricId))
  const group = canned?.groups?.find((item) => item.metric_id === metricId)
  if (group && group.clusters.length > 0) {
    return [...group.clusters]
      .sort((a, b) => b.count - a.count)
      .map((cluster) => fromCanned(cluster, group.flagged_count || failing.length))
  }
  const derived = deriveFromCalls(metricId, metricName, failing)
  if (derived.length > 0) return derived
  const hints = globalMetricById(metricId)?.improvementHints ?? []
  if (hints.length === 0 || failing.length === 0) return []
  return hints.map((hint, index) => ({
    id: `hint-${metricId}-${index}`,
    label: index === 0 ? 'Majority failure pattern' : 'Also consider',
    gapLabel: null,
    count: failing.length,
    sharePct: index === 0 ? 100 : 0,
    observation: hint,
    evidence: failing[0]?.turns.find((turn) => turn.toolCall?.failed || turn.ragCall?.failed)?.text ?? null,
    suggestedPrompt: hint,
  }))
}
