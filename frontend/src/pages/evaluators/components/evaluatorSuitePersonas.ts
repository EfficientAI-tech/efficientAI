import type { EvaluatorSuite } from '../../../lib/api'
import { isChatMedium } from '../../../lib/agentMedium'

export function isChatEvaluatorSuite(suite: { agent_call_medium?: string | null }): boolean {
  return isChatMedium(suite.agent_call_medium)
}

export function formatSuiteDisplayName(suite: EvaluatorSuite): string {
  const name = suite.name?.trim()
  if (name) return name
  if (isChatEvaluatorSuite(suite)) {
    return suite.agent_name || 'Suite'
  }
  return `${suite.agent_name || 'Suite'} · ${suite.persona_name || 'Persona'}`
}

export function formatSuitePersonaLabel(suite: EvaluatorSuite): string {
  if (isChatEvaluatorSuite(suite)) return '—'
  const personas = suite.personas ?? []
  if (personas.length > 1) {
    const names = personas.map((p) => p.name).filter(Boolean)
    if (names.length > 0) return names.join(', ')
    return `${personas.length} personas`
  }
  return suite.persona_name || '—'
}

export function formatSuiteCombinationSummary(
  suite: { agent_call_medium?: string | null },
  personaCount: number,
  distinctScenarioCount: number,
): string {
  if (isChatEvaluatorSuite(suite)) {
    return `${distinctScenarioCount} scenario${distinctScenarioCount !== 1 ? 's' : ''}`
  }
  const comboPart = `${personaCount} persona${personaCount !== 1 ? 's' : ''} × ${distinctScenarioCount} scenario${distinctScenarioCount !== 1 ? 's' : ''}`
  return comboPart
}
