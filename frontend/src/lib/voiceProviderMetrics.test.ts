import { describe, expect, it } from 'vitest'
import { extractProviderCostSummary, formatProviderCostAmount } from './voiceProviderMetrics'

describe('extractProviderCostSummary', () => {
  it('converts Retell combined_cost from cents to dollars', () => {
    const summary = extractProviderCostSummary('retell', {
      call_cost: { combined_cost: 3.44 },
    })
    expect(summary).toEqual({ total: 0.0344, unit: 'usd' })
  })

  it('uses ElevenLabs fiat cost with credits note', () => {
    const summary = extractProviderCostSummary('elevenlabs', {
      cost: 523,
      raw_data: {
        metadata: {
          cost: 523,
          cost_fiat: 0.062761,
        },
      },
    })
    expect(summary).toEqual({ total: 0.062761, unit: 'usd', creditNote: 523 })
  })

  it('reads Smallest credits from callCost', () => {
    const summary = extractProviderCostSummary('smallest', {
      raw_data: {
        callCost: {
          callCharge: 120,
          llmCharge: 15,
        },
      },
    })
    expect(summary).toEqual({ total: 135, unit: 'credits' })
  })
})

describe('formatProviderCostAmount', () => {
  it('formats credits and usd differently', () => {
    expect(formatProviderCostAmount(135, 'credits')).toBe('135 credits')
    expect(formatProviderCostAmount(0.0344, 'usd')).toBe('$0.0344')
  })
})
