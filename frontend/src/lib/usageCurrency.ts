import { formatCompactCostMagnitude } from './usageFormatters'

export type UsageDisplayCurrency = 'USD' | 'INR'

const STORAGE_KEY = 'efficientai.usage.displayCurrency'

export function getUsageDisplayCurrency(): UsageDisplayCurrency {
  if (typeof window === 'undefined') return 'USD'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'INR' ? 'INR' : 'USD'
}

export function setUsageDisplayCurrency(currency: UsageDisplayCurrency): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(STORAGE_KEY, currency)
}

function displayAmount(
  usd: number | null | undefined,
  currency: UsageDisplayCurrency,
  inrRate: number,
): number | null {
  const amountUsd = Number(usd || 0)
  if (!amountUsd) return null
  return currency === 'INR' ? amountUsd * inrRate : amountUsd
}

function formatUsdAmount(amountUsd: number): string {
  const abs = Math.abs(amountUsd)
  const digits = abs >= 1 ? 2 : 4
  const sign = amountUsd < 0 ? '-' : ''
  return `${sign}$${Math.abs(amountUsd).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`
}

function formatInrAmount(amountInr: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amountInr)
}

function formatExactMoney(amount: number, currency: UsageDisplayCurrency): string {
  return currency === 'INR' ? formatInrAmount(amount) : formatUsdAmount(amount)
}

function formatCompactMoney(amount: number, currency: UsageDisplayCurrency): string | null {
  const compact = formatCompactCostMagnitude(Math.abs(amount))
  if (!compact) return null
  const symbol = currency === 'INR' ? '₹' : '$'
  return `${amount < 0 ? '-' : ''}${symbol}${compact}`
}

/** Exact 2-decimal cost below 1 lakh. Above that, compact with more decimals at each unit. */
export function formatUsageCostUsd(
  usd: number | null | undefined,
  currency: UsageDisplayCurrency,
  inrRate: number,
): string {
  const amount = displayAmount(usd, currency, inrRate)
  if (amount == null) return '—'
  return formatCompactMoney(amount, currency) ?? formatExactMoney(amount, currency)
}

/** Full cost for hover tooltips and the breakdown modal. */
export function formatUsageCostExactUsd(
  usd: number | null | undefined,
  currency: UsageDisplayCurrency,
  inrRate: number,
): string {
  const amount = displayAmount(usd, currency, inrRate)
  if (amount == null) return '—'
  return formatExactMoney(amount, currency)
}

export function formatFxRateHint(
  inrRate: number,
  asOf?: string | null,
  source?: string | null,
): string {
  if (source === 'default') {
    return `1 USD ≈ ₹${inrRate.toFixed(2)} (estimate — live FX unavailable)`
  }
  const dateLabel = asOf ? asOf.slice(0, 10) : 'today'
  return `1 USD = ₹${inrRate.toFixed(2)} (Frankfurter, ${dateLabel})`
}
