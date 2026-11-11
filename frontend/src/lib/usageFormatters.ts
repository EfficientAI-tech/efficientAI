const TIERS = [
  { value: 1e12, suffix: 'T', decimals: 3 },
  { value: 1e9, suffix: 'B', decimals: 3 },
  { value: 1e6, suffix: 'M', decimals: 2 },
  { value: 1e3, suffix: 'K', decimals: 1 },
] as const

function finiteNumber(value: number): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function trimFixed(value: number, digits: number): string {
  return value.toFixed(digits).replace(/\.0+$/, '').replace(/(\.\d*[1-9])0+$/, '$1')
}

/** Round up to `digits` places. Exact values stay put (1.50 does not become 1.51). */
function ceilTo(value: number, digits: number): number {
  const factor = 10 ** digits
  const scaled = value * factor
  const nearest = Math.round(scaled)
  if (Math.abs(scaled - nearest) < 1e-6) return nearest / factor
  return Math.ceil(scaled - 1e-8) / factor
}

/**
 * Compact magnitude. Decimals grow with the unit (K 1, M 2, B/T 3) and the
 * short figure is rounded up so it is never smaller than the real number.
 * Returns null below 1,000.
 */
export function formatCompactMagnitude(abs: number): string | null {
  if (!(abs >= 1000)) return null
  for (let i = 0; i < TIERS.length; i++) {
    const tier = TIERS[i]
    if (abs < tier.value) continue
    let rounded = ceilTo(abs / tier.value, tier.decimals)
    let decimals: number = tier.decimals
    let suffix: string = tier.suffix
    if (rounded >= 1000 && i > 0) {
      const higher = TIERS[i - 1]
      rounded = ceilTo(abs / higher.value, higher.decimals)
      decimals = higher.decimals
      suffix = higher.suffix
    }
    return `${trimFixed(rounded, decimals)}${suffix}`
  }
  return null
}

const COST_COMPACT_FROM = 100_000
const COST_TIER_DECIMALS = { K: 2, M: 3, B: 4, T: 4 } as const

/** Nearest value at `digits` places. Exact values are left unchanged. */
function roundHalfUp(value: number, digits: number): number {
  const factor = 10 ** digits
  return Math.round((value + Number.EPSILON) * factor) / factor
}

/**
 * Cost compact form. Amounts under 1 lakh stay exact at 2 decimal places.
 * Above that: K keeps 2 decimals, millions 3, and billions or more stop at 4.
 */
export function formatCompactCostMagnitude(abs: number): string | null {
  if (!(abs >= COST_COMPACT_FROM)) return null
  for (let i = 0; i < TIERS.length; i++) {
    const tier = TIERS[i]
    if (abs < tier.value) continue
    let decimals: number = COST_TIER_DECIMALS[tier.suffix]
    let rounded = roundHalfUp(abs / tier.value, decimals)
    let suffix: string = tier.suffix
    if (rounded >= 1000 && i > 0) {
      const higher = TIERS[i - 1]
      decimals = COST_TIER_DECIMALS[higher.suffix]
      rounded = roundHalfUp(abs / higher.value, decimals)
      suffix = higher.suffix
    }
    return `${trimFixed(rounded, decimals)}${suffix}`
  }
  return null
}

/** Token / call / character counts: exact below 1,000, otherwise `K`/`M`/`B`/`T`. */
export function formatCompactCount(value: number): string {
  const n = Math.round(finiteNumber(value))
  const sign = n < 0 ? '-' : ''
  const abs = Math.abs(n)
  if (abs < 1000) return `${sign}${abs}`
  return `${sign}${formatCompactMagnitude(abs) ?? String(abs)}`
}

export function formatExactCount(value: number): string {
  return new Intl.NumberFormat('en-US').format(Math.round(finiteNumber(value)))
}

/** Primary STT duration. Hours drop leftover seconds so the cell stays short. */
export function formatAudioDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(finiteNumber(seconds)))
  if (total < 60) return `${total}s`
  const mins = Math.floor(total / 60)
  const secs = total % 60
  if (mins < 60) return secs ? `${mins}m ${secs}s` : `${mins}m`
  const hours = Math.floor(mins / 60)
  const remMins = mins % 60
  return remMins ? `${hours}h ${remMins}m` : `${hours}h`
}

/** Exact duration for hover, including leftover seconds and the raw total. */
export function formatAudioExact(seconds: number): string {
  const total = Math.max(0, Math.floor(finiteNumber(seconds)))
  const hours = Math.floor(total / 3600)
  const mins = Math.floor((total % 3600) / 60)
  const secs = total % 60
  const clock = hours
    ? `${hours}h ${mins}m ${secs}s`
    : mins
      ? `${mins}m ${secs}s`
      : `${secs}s`
  return `${clock} (${formatExactCount(total)}s)`
}
