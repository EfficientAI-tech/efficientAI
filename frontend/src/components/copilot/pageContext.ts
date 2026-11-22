import type { CopilotPageContext } from '../../lib/copilotApi'

const PATTERNS: { re: RegExp; entity: (m: RegExpMatchArray) => Omit<CopilotPageContext, 'route'> }[] = [
  {
    re: /^\/call-imports\/([^/]+)\/evaluations\/([^/]+)/,
    entity: (m) => ({ entity_type: 'import_evaluation', entity_id: m[2], title: `Import ${m[1]}` }),
  },
  { re: /^\/call-imports\/(?!tags|schemas)([^/]+)/, entity: (m) => ({ entity_type: 'call_import', entity_id: m[1] }) },
  { re: /^\/call-imports\/?$/, entity: () => ({ entity_type: 'call_import_list' }) },
  { re: /^\/agents\/([^/]+)/, entity: (m) => ({ entity_type: 'agent', entity_id: m[1] }) },
  { re: /^\/agents\/?$/, entity: () => ({ entity_type: 'agent_list' }) },
  { re: /^\/simulations\/([^/]+)/, entity: (m) => ({ entity_type: 'simulation_run', entity_id: m[1] }) },
  { re: /^\/results\/(?!agents|unassigned)([^/]+)/, entity: (m) => ({ entity_type: 'test_call', entity_id: m[1] }) },
  { re: /^\/personas/, entity: () => ({ entity_type: 'persona_list' }) },
  { re: /^\/scenarios/, entity: () => ({ entity_type: 'scenario_list' }) },
  { re: /^\/evaluate-test-agents\/([^/]+)/, entity: (m) => ({ entity_type: 'evaluator_suite', entity_id: m[1] }) },
  { re: /^\/metrics-management/, entity: () => ({ entity_type: 'metrics' }) },
]

/** What the user is looking at, sent with each message so "this" resolves. Ids only, never page data. */
export function pageContextFromPath(pathname: string): CopilotPageContext {
  const route = pathname.slice(0, 300)
  for (const { re, entity } of PATTERNS) {
    const match = pathname.match(re)
    if (match) return { route, ...entity(match) }
  }
  return { route }
}
