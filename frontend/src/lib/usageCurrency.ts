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

function formatUsdAmount(amountUsd: number): string {
  const abs = Math.abs(amountUsd)
  const digits = abs >= 1 ? 2 : 4
  return `$${amountUsd.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`
}

export function formatUsageCostUsd(
  usd: number | null | undefined,
  currency: UsageDisplayCurrency,
  inrRate: number,
): string {
  const amountUsd = Number(usd || 0)
  if (!amountUsd) return '—'
  if (currency === 'INR') {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amountUsd * inrRate)
  }
  return formatUsdAmount(amountUsd)
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
