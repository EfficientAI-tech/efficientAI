import { describe, expect, it } from 'vitest'
import {
  compactStudioScoreLabel,
  studioMetricRationale,
} from './studioResultScoreDisplay'

describe('compactStudioScoreLabel', () => {
  it('formats boolean and empty scores', () => {
    expect(compactStudioScoreLabel(undefined)).toBe('—')
    expect(compactStudioScoreLabel({ type: 'boolean', value: true })).toBe('Yes')
    expect(compactStudioScoreLabel({ type: 'boolean', value: false })).toBe('No')
  })

  it('extracts trimmed rationales', () => {
    expect(studioMetricRationale(undefined)).toBeUndefined()
    expect(studioMetricRationale({ rationale: '  hello  ' })).toBe('hello')
    expect(studioMetricRationale({ rationale: '   ' })).toBeUndefined()
  })
})