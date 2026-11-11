import { describe, expect, it } from 'vitest'
import {
  formatAudioDuration,
  formatAudioExact,
  formatCompactCount,
  formatExactCount,
} from './usageFormatters'
import { formatUsageCostExactUsd, formatUsageCostUsd } from './usageCurrency'

describe('formatCompactCount', () => {
  it('keeps small counts exact and compacts the rest', () => {
    expect(formatCompactCount(0)).toBe('0')
    expect(formatCompactCount(999)).toBe('999')
    expect(formatCompactCount(1_000)).toBe('1K')
    expect(formatCompactCount(46_640)).toBe('46.7K')
    expect(formatCompactCount(194_826)).toBe('194.9K')
    expect(formatCompactCount(999_950)).toBe('1M')
    expect(formatCompactCount(1_008_146)).toBe('1.01M')
    expect(formatCompactCount(2_472_082)).toBe('2.48M')
    expect(formatCompactCount(342_616_620)).toBe('342.62M')
    expect(formatCompactCount(1_500_000_000)).toBe('1.5B')
    expect(formatCompactCount(14_049_396_030)).toBe('14.05B')
  })

  it.each([
    [0, '0'],
    [1, '1'],
    [42, '42'],
    [999, '999'],
    [1_000, '1K'],
    [1_001, '1.1K'],
    [1_500, '1.5K'],
    [9_949, '10K'],
    [46_640, '46.7K'],
    [194_826, '194.9K'],
    [999_949, '1M'],
    [1_000_000, '1M'],
    [1_000_001, '1.01M'],
    [1_010_000, '1.01M'],
    [2_472_082, '2.48M'],
    [342_616_620, '342.62M'],
    [999_999_999, '1B'],
    [1_000_000_000, '1B'],
    [1_000_000_001, '1.001B'],
    [1_500_000_000, '1.5B'],
    [14_049_396_030, '14.05B'],
    [999_999_999_999, '1T'],
    [1_000_000_000_000, '1T'],
    [1_234_567_890_123, '1.235T'],
  ])('shows %d as %s', (value, expected) => {
    expect(formatCompactCount(value)).toBe(expected)
    expect(formatExactCount(value)).toBe(new Intl.NumberFormat('en-US').format(value))
  })
})

describe('formatExactCount', () => {
  it('groups the full integer', () => {
    expect(formatExactCount(342_616_620)).toBe('342,616,620')
    expect(formatExactCount(0)).toBe('0')
  })
})

describe('audio duration', () => {
  it('keeps the short clock and spells out leftover seconds on hover', () => {
    expect(formatAudioDuration(45)).toBe('45s')
    expect(formatAudioDuration(505 * 3600 + 12 * 60 + 18)).toBe('505h 12m')
    expect(formatAudioExact(505 * 3600 + 12 * 60 + 18)).toBe('505h 12m 18s (1,818,738s)')
    expect(formatAudioExact(45)).toBe('45s (45s)')
  })
})

describe('usage cost formatting', () => {
  it('compacts large USD and INR amounts and keeps the exact value separate', () => {
    expect(formatUsageCostUsd(0.0042, 'USD', 95)).toBe('$0.0042')
    expect(formatUsageCostExactUsd(0.0042, 'USD', 95)).toBe('$0.0042')
    expect(formatUsageCostUsd(1250, 'USD', 95)).toBe('$1,250.00')
    expect(formatUsageCostUsd(9593.46, 'USD', 95)).toBe('$9,593.46')
    expect(formatUsageCostUsd(22824.78, 'USD', 95)).toBe('$22,824.78')
    expect(formatUsageCostExactUsd(22824.78, 'USD', 95)).toBe('$22,824.78')
    expect(formatUsageCostExactUsd(662.675, 'USD', 95)).toBe('$662.68')

    expect(formatUsageCostUsd(62954.12 / 95, 'INR', 95)).toBe('₹62,954.12')
    expect(formatUsageCostExactUsd(62954.12 / 95, 'INR', 95)).toBe('₹62,954.12')
    expect(formatUsageCostUsd(1_250_000 / 95, 'INR', 95)).toBe('₹1.25M')
    expect(formatUsageCostUsd(640.2 / 95, 'INR', 95)).toBe('₹640.20')
  })

  it.each([
    [0.0042, '$0.0042', '$0.0042'],
    [0.5, '$0.5000', '$0.5000'],
    [1, '$1.00', '$1.00'],
    [662.68, '$662.68', '$662.68'],
    [1_250, '$1,250.00', '$1,250.00'],
    [9_593.46, '$9,593.46', '$9,593.46'],
    [9_999.99, '$9,999.99', '$9,999.99'],
    [10_000, '$10,000.00', '$10,000.00'],
    [22_824.78, '$22,824.78', '$22,824.78'],
    [99_999.99, '$99,999.99', '$99,999.99'],
    [99_999.996, '$100K', '$100,000.00'],
    [100_000, '$100K', '$100,000.00'],
    [100_050, '$100.05K', '$100,050.00'],
    [250_000.49, '$250K', '$250,000.49'],
    [999_999.4, '$1M', '$999,999.40'],
    [1_000_000, '$1M', '$1,000,000.00'],
    [1_234_567.89, '$1.235M', '$1,234,567.89'],
    [1_250_000, '$1.25M', '$1,250,000.00'],
    [1_000_000_000, '$1B', '$1,000,000,000.00'],
    [1_234_567_890.12, '$1.2346B', '$1,234,567,890.12'],
    [1_000_000_000_000, '$1T', '$1,000,000,000,000.00'],
    [1_234_567_890_123.45, '$1.2346T', '$1,234,567,890,123.45'],
  ])('USD %d shows %s and hovers %s', (usd, compact, exact) => {
    expect(formatUsageCostUsd(usd, 'USD', 1)).toBe(compact)
    expect(formatUsageCostExactUsd(usd, 'USD', 1)).toBe(exact)
  })

  it.each([
    [0.5, '₹0.50', '₹0.50'],
    [640.2, '₹640.20', '₹640.20'],
    [9_999.99, '₹9,999.99', '₹9,999.99'],
    [62_954.12, '₹62,954.12', '₹62,954.12'],
    [99_999.99, '₹99,999.99', '₹99,999.99'],
    [100_000, '₹100K', '₹1,00,000.00'],
    [1_250_000, '₹1.25M', '₹12,50,000.00'],
    [1_000_000_000, '₹1B', '₹1,00,00,00,000.00'],
    [1_000_000_000_000, '₹1T', '₹10,00,00,00,00,000.00'],
  ])('INR %d shows %s and hovers %s', (inr, compact, exact) => {
    expect(formatUsageCostUsd(inr, 'INR', 1)).toBe(compact)
    expect(formatUsageCostExactUsd(inr, 'INR', 1)).toBe(exact)
  })
})
