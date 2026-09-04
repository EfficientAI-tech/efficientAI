import type { EvaluatorSuite } from '../../../lib/api'

export function formatSuitePersonaLabel(suite: EvaluatorSuite): string {
  const personas = suite.personas ?? []
  if (personas.length > 1) {
    const names = personas.map((p) => p.name).filter(Boolean)
    if (names.length > 0) return names.join(', ')
    return `${personas.length} personas`
  }
  return suite.persona_name || '—'
}
