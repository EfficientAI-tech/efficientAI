import type { Scenario } from './scenarioTypes'

export type PlannedScenarioMetricType = 'auto' | 'boolean' | 'rating' | 'number' | 'text'

export interface GeneratedScenarioMetricDraft {
  name: string
  description: string
  metric_type: 'rating' | 'boolean' | 'number' | 'text'
  custom_data_type: 'boolean' | 'enum' | 'number_range' | null
  custom_config: Record<string, unknown>
  supported_surfaces: string[]
  enabled_surfaces: string[]
  tags: string[]
}

export interface ScenarioMetricWorkflowDraft {
  id: string
  name: string
  description: string
  goal?: string
  plannedMetricType: PlannedScenarioMetricType
  sourceScenarioId?: string
  metric?: GeneratedScenarioMetricDraft
  metricPushed?: boolean
}

export function scenarioGoalFromRequiredInfo(required_info: Record<string, string>): string | undefined {
  const goal = required_info.goal ?? required_info.Goal
  return goal?.trim() || undefined
}

export function scenarioToMetricWorkflowDraft(scenario: Scenario): ScenarioMetricWorkflowDraft {
  return {
    id: scenario.id,
    sourceScenarioId: scenario.id,
    name: scenario.name,
    description: scenario.description || '',
    goal: scenarioGoalFromRequiredInfo(scenario.required_info),
    plannedMetricType: 'auto',
  }
}

export function mergeRequiredMetricTags(tags: string[], agentName: string): string[] {
  const required = [agentName.trim(), 'auto-generated'].filter(Boolean)
  const seen = new Set<string>()
  const merged: string[] = []
  for (const tag of required) {
    if (!seen.has(tag)) {
      seen.add(tag)
      merged.push(tag)
    }
  }
  for (const tag of tags) {
    const trimmed = tag.trim()
    if (trimmed && !seen.has(trimmed)) {
      seen.add(trimmed)
      merged.push(trimmed)
    }
  }
  return merged
}

export function customDataTypeForMetricType(
  metricType: GeneratedScenarioMetricDraft['metric_type']
): GeneratedScenarioMetricDraft['custom_data_type'] {
  if (metricType === 'boolean') return 'boolean'
  if (metricType === 'number') return 'number_range'
  if (metricType === 'text') return null
  return 'enum'
}

export const MAX_SCENARIO_METRICS_BATCH = 10
