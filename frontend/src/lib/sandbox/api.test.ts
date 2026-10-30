import { describe, expect, it } from 'vitest'
import { sandboxApi } from './api'

describe('sandboxApi', () => {
  it('lists fixture sessions including simulation and manual kinds', () => {
    const items = sandboxApi.listSessions()
    expect(items.some((i) => i.kind === 'simulation')).toBe(true)
    expect(items.some((i) => i.kind === 'manual')).toBe(true)
    expect(items.find((i) => i.id === 'sim-success')).toBeTruthy()
  })

  it('remembers an API failure dismissal on the main records agent', () => {
    const session = sandboxApi.getSession('sim-breakage')
    expect(session).toBeTruthy()
    const apiIssue = session!.issues.find((i) => i.category === 'external_api_failure')
    expect(apiIssue?.status).toBe('dismissed')
    expect(apiIssue?.rememberedFromSessionId).toBe('sim-prior')
    expect(session!.issues.filter((i) => i.status === 'open').length).toBeGreaterThan(0)
  })

  it('keeps the same issues open for a different agent', () => {
    const session = sandboxApi.getSession('sim-breakage-alt')
    const apiIssue = session!.issues.find((i) => i.category === 'external_api_failure')
    expect(apiIssue?.status).toBe('open')
  })

  it('creates a manual chat defaulting to the main agent', () => {
    const chat = sandboxApi.createManualChat({
      environmentId: 'env-records',
      agent: sandboxApi.emptyAgentConfig('A'),
      target: 'A',
    })
    expect(chat.kind).toBe('manual')
    expect(chat.chatTarget).toBe('A')
    const next = sandboxApi.sendMessage({ sessionId: chat.id, text: 'Fetch ENT-1001' })
    expect(next.turns.some((t) => t.speaker === 'human')).toBe(true)
    expect(next.turns.some((t) => t.speaker === 'A')).toBe(true)
  })
})
