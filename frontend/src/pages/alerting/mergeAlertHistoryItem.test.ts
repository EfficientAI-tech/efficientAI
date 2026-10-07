import { describe, expect, it } from 'vitest'
import { mergeAlertHistoryItem, normalizeHistoryStatus } from './mergeAlertHistoryItem'

describe('mergeAlertHistoryItem', () => {
  const base = {
    id: 'h1',
    status: 'notified',
    triggered_at: 't',
    triggered_value: 1,
    threshold_value: 1,
    alert: { name: 'Rule A' },
    notification_details: { results: [{ success: true }] },
  }

  it('preserves alert when API omits it', () => {
    const merged = mergeAlertHistoryItem(base, {
      id: 'h1',
      status: 'acknowledged',
      acknowledged_at: 'x',
      notification_details: {
        results: [{ success: true }],
        lifecycle: { acknowledge: [{ success: true, channel: 'pagerduty_acknowledge' }] },
      },
    })
    expect(merged.alert?.name).toBe('Rule A')
    expect(merged.status).toBe('acknowledged')
    expect(merged.notification_details?.lifecycle).toBeTruthy()
  })

  it('does not wipe notification_details on empty object', () => {
    const merged = mergeAlertHistoryItem(base, { id: 'h1', status: 'acknowledged', notification_details: {} })
    expect(merged.notification_details?.results).toBeTruthy()
  })
})

describe('normalizeHistoryStatus', () => {
  it('lowercases strings', () => {
    expect(normalizeHistoryStatus('ACKNOWLEDGED')).toBe('acknowledged')
  })
})
