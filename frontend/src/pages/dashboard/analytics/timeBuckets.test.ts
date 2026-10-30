import { describe, expect, it } from 'vitest'
import { bucketsForRange, parseRange, parseSource } from './timeBuckets'

describe('bucketsForRange', () => {
  const now = new Date('2026-10-22T15:30:00')

  it('returns 7 daily buckets for 7d', () => {
    const result = bucketsForRange('7d', now)
    expect(result.rangeDays).toBe(7)
    expect(result.buckets).toHaveLength(7)
    expect(result.current.start.toDateString()).toBe(new Date(2026, 9, 16).toDateString())
    expect(result.previous.end.toDateString()).toBe(new Date(2026, 9, 15).toDateString())
    expect(result.previousRangeLabel).toBe('previous 7 days')
  })

  it('returns 5 buckets for 30d and 13 for 90d', () => {
    expect(bucketsForRange('30d', now).buckets).toHaveLength(5)
    expect(bucketsForRange('90d', now).buckets).toHaveLength(13)
    expect(bucketsForRange('30d', now).rangeDays).toBe(30)
    expect(bucketsForRange('90d', now).rangeDays).toBe(90)
  })

  it('keeps previous window the same length as current', () => {
    const result = bucketsForRange('7d', now)
    const currentMs = result.current.end.getTime() - result.current.start.getTime()
    const previousMs = result.previous.end.getTime() - result.previous.start.getTime()
    expect(Math.abs(currentMs - previousMs)).toBeLessThan(2 * 60 * 60 * 1000)
  })
})

describe('parse helpers', () => {
  it('parses range and source with defaults', () => {
    expect(parseRange('30d')).toBe('30d')
    expect(parseRange('nope')).toBe('7d')
    expect(parseSource('live')).toBe('live')
    expect(parseSource(null)).toBe('simulation')
  })
})
