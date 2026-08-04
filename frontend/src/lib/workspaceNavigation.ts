/**
 * Maps workspace-scoped detail URLs to their parent list route when the
 * active workspace changes. More-specific patterns must appear first.
 */
const WORKSPACE_DETAIL_REDIRECTS: Array<{ pattern: RegExp; parent: string }> = [
  { pattern: /^\/call-imports\/[^/]+\/evaluations\/[^/]+$/, parent: '/call-imports' },
  { pattern: /^\/call-imports\/[^/]+$/, parent: '/call-imports' },
  { pattern: /^\/evaluations\/[^/]+$/, parent: '/evaluations' },
  {
    pattern: /^\/results\/agents\/[^/]+\/suites\/[^/]+\/scenarios\/[^/]+$/,
    parent: '/results',
  },
  { pattern: /^\/results\/agents\/[^/]+\/suites\/[^/]+$/, parent: '/results' },
  { pattern: /^\/results\/agents\/[^/]+$/, parent: '/results' },
  { pattern: /^\/results\/unassigned$/, parent: '/results' },
  { pattern: /^\/results\/[^/]+$/, parent: '/results' },
  { pattern: /^\/evaluate-test-agents\/[^/]+$/, parent: '/evaluate-test-agents' },
  { pattern: /^\/agents\/[^/]+$/, parent: '/agents' },
  { pattern: /^\/playground\/call-recordings\/[^/]+$/, parent: '/playground' },
  { pattern: /^\/playground\/test-agent-results\/[^/]+$/, parent: '/playground' },
  { pattern: /^\/observability\/calls\/[^/]+$/, parent: '/observability/calls' },
  { pattern: /^\/judge-alignment\/datasets\/[^/]+$/, parent: '/judge-alignment' },
  { pattern: /^\/prompt-partials\/[^/]+$/, parent: '/prompt-partials' },
]

/**
 * Returns the list-route to navigate to when switching workspaces from a
 * detail page, or null if the current path is already a list/sub-page.
 */
export function resolveWorkspaceSwitchPath(pathname: string): string | null {
  for (const { pattern, parent } of WORKSPACE_DETAIL_REDIRECTS) {
    if (pattern.test(pathname)) {
      return parent
    }
  }
  return null
}
