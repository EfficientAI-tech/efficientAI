import { describe, expect, it } from 'vitest'
import {
  buildIncidentTimeline,
  collectChannelAttempts,
  hasLifecycleSyncActivity,
} from './incidentActivityUtils'

describe('collectChannelAttempts', () => {
  it('merges initial and lifecycle phases', () => {
    const attempts = collectChannelAttempts({
      results: [{ channel: 'pagerduty', success: true }],
      lifecycle: {
        acknowledge: [{ channel: 'pagerduty_acknowledge', success: true }],
        recovery: [{ channel: 'slack_recovery', success: false, error: 'timeout' }],
      },
    })
    expect(attempts).toHaveLength(3)
    expect(attempts.map(a => a.phase)).toEqual(['initial', 'acknowledge', 'recovery'])
  })

  it('handles null safely', () => {
    expect(collectChannelAttempts(null)).toEqual([])
    expect(collectChannelAttempts(undefined)).toEqual([])
  })
})

describe('hasLifecycleSyncActivity', () => {
  it('is false for fire-only details', () => {
    expect(hasLifecycleSyncActivity({ results: [{ success: true }] })).toBe(false)
  })

  it('is true when lifecycle present', () => {
    expect(
      hasLifecycleSyncActivity({ lifecycle: { acknowledge: [{ success: true }] } })
    ).toBe(true)
  })
})

describe('buildIncidentTimeline', () => {
  it('orders lifecycle steps', () => {
    const steps = buildIncidentTimeline({
      triggered_at: '2026-01-01T12:00:00Z',
      notified_at: '2026-01-01T12:01:00Z',
      acknowledged_at: '2026-01-01T12:05:00Z',
      status: 'acknowledged',
      acknowledged_by: 'user@test.com',
    })
    expect(steps.map(s => s.key)).toEqual(['triggered', 'notified', 'ack'])
  })

  it('shows auto-resolve copy for system resolver', () => {
    const steps = buildIncidentTimeline({
      triggered_at: '2026-01-01T12:00:00Z',
      resolved_at: '2026-01-01T12:20:00Z',
      status: 'resolved',
      resolved_by: 'system',
      context_data: { auto_resolved: true },
    })
    expect(steps.some(s => s.title === 'Auto-resolved')).toBe(true)
  })
})
