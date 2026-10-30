import { failsRule, globalMetricById } from './globalMetrics'
import type { MockCall } from './mockCalls'

export function callGlobalValue(call: MockCall, metricId: string): number | null {
  const global = globalMetricById(metricId)
  if (!global) return null
  const computed = call.computed
  switch (global.id) {
    case 'avg_duration':
      return computed.durationSeconds
    case 'closing_quality':
      return computed.closingQuality
    case 'early_ending':
      return computed.earlyEnding
    case 'silence_duration':
      return computed.silenceAvgSeconds
    case 'longest_pause':
      return computed.silenceMaxSeconds
    case 'tool_call_failures':
      return computed.toolCallFailures
    case 'rag_call_failures':
      return computed.ragCallFailures
    case 'talk_ratio':
      return computed.talkRatio
    default:
      return null
  }
}

export function callFailed(call: MockCall, metricId: string): boolean {
  const global = globalMetricById(metricId)
  if (global) {
    const value = callGlobalValue(call, metricId)
    if (value == null) return false
    return failsRule(value, global.failRule)
  }
  return Boolean(call.metric_scores[metricId]?.failed)
}
