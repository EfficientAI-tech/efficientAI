import { describe, expect, it } from 'vitest'
import {
  DEFAULT_AGENT_PLAYGROUND_TAB,
  agentPlaygroundPath,
  parseAgentPlaygroundTab,
} from './playgroundAgentTabs'

describe('playgroundAgentTabs', () => {
  it('parses the sandbox tab from search params', () => {
    expect(parseAgentPlaygroundTab(new URLSearchParams('tab=sandbox'))).toBe('sandbox')
  })

  it('falls back to the default tab for unknown values', () => {
    expect(parseAgentPlaygroundTab(new URLSearchParams('tab=nope'))).toBe(DEFAULT_AGENT_PLAYGROUND_TAB)
  })

  it('builds the sandbox deep link', () => {
    expect(agentPlaygroundPath('sandbox')).toBe('/playground?tab=sandbox')
  })
})
