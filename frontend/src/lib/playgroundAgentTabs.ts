export type AgentPlaygroundTab = 'test_agents' | 'voice_ai_agents' | 'custom_websocket'

const VALID_TABS = new Set<AgentPlaygroundTab>([
  'test_agents',
  'voice_ai_agents',
  'custom_websocket',
])

export const DEFAULT_AGENT_PLAYGROUND_TAB: AgentPlaygroundTab = 'voice_ai_agents'

export function parseAgentPlaygroundTab(searchParams: URLSearchParams): AgentPlaygroundTab {
  const raw = searchParams.get('tab')
  if (raw && VALID_TABS.has(raw as AgentPlaygroundTab)) {
    return raw as AgentPlaygroundTab
  }
  return DEFAULT_AGENT_PLAYGROUND_TAB
}

export function agentPlaygroundPath(tab?: AgentPlaygroundTab | null): string {
  const resolved = tab ?? DEFAULT_AGENT_PLAYGROUND_TAB
  if (resolved === DEFAULT_AGENT_PLAYGROUND_TAB) {
    return '/playground'
  }
  return `/playground?tab=${resolved}`
}

export function agentPlaygroundTabFromProviderPlatform(
  platform: string | null | undefined,
): AgentPlaygroundTab {
  if ((platform || '').toLowerCase() === 'custom_websocket') {
    return 'custom_websocket'
  }
  return 'voice_ai_agents'
}
