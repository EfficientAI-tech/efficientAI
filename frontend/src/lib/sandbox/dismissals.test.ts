import { describe, expect, it } from 'vitest'
import { applyRememberedDismissals, issueSignature, removeDismissal, upsertDismissal } from './dismissals'
import type { AgentDismissal, Issue } from './types'

const issue = (overrides?: Partial<Issue>): Issue => ({
  id: 'iss-1',
  severity: 'error',
  category: 'external_api_failure',
  source: 'rule',
  agent: 'A',
  title: 'orders-api failed',
  whatHappened: '503',
  whatToCheck: 'credential',
  eventIds: [],
  status: 'open',
  configRef: { agent: 'A', section: 'tools', itemId: 'orders-api' },
  ...overrides,
})

describe('issueSignature', () => {
  it('joins category and item id', () => {
    expect(issueSignature(issue())).toBe('external_api_failure:orders-api')
  })

  it('falls back when config item is missing', () => {
    expect(issueSignature(issue({ configRef: undefined }))).toBe('external_api_failure:unknown')
  })
})

describe('applyRememberedDismissals', () => {
  const remembered: AgentDismissal = {
    agentId: 'agent-records-bot',
    signature: 'external_api_failure:orders-api',
    dismissedAt: '2026-01-01T00:00:00.000Z',
    sourceSessionId: 'sim-prior',
    reason: 'Known outage',
  }

  it('dismisses matching issues for the same agent', () => {
    const [applied] = applyRememberedDismissals([issue()], [remembered], 'agent-records-bot')
    expect(applied.status).toBe('dismissed')
    expect(applied.rememberedFromSessionId).toBe('sim-prior')
    expect(applied.dismissReason).toBe('Known outage')
  })

  it('leaves issues open for a different agent', () => {
    const [applied] = applyRememberedDismissals([issue()], [remembered], 'agent-records-bot-alt')
    expect(applied.status).toBe('open')
    expect(applied.rememberedFromSessionId).toBeUndefined()
  })

  it('does not hide a different tool failure', () => {
    const other = issue({
      category: 'tool_failed',
      configRef: { agent: 'A', section: 'tools', itemId: 'get_entry' },
    })
    const [applied] = applyRememberedDismissals([other], [remembered], 'agent-records-bot')
    expect(applied.status).toBe('open')
  })
})

describe('upsertDismissal / removeDismissal', () => {
  it('replaces the same signature for an agent', () => {
    const first: AgentDismissal = {
      agentId: 'a1',
      signature: 'tool_failed:get_entry',
      dismissedAt: '1',
      sourceSessionId: 's1',
    }
    const second: AgentDismissal = { ...first, reason: 'updated', dismissedAt: '2' }
    const next = upsertDismissal([first], second)
    expect(next).toHaveLength(1)
    expect(next[0].reason).toBe('updated')
  })

  it('removes a stored dismissal', () => {
    const stored: AgentDismissal = {
      agentId: 'a1',
      signature: 'tool_failed:get_entry',
      dismissedAt: '1',
      sourceSessionId: 's1',
    }
    expect(removeDismissal([stored], 'tool_failed:get_entry', 'a1')).toEqual([])
  })
})
