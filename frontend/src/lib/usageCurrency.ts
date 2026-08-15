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

export function formatUsageCostUsd(
  usd: number | null | undefined,
  currency: UsageDisplayCurrency,
  inrRate: number,
): string {
  const amountUsd = Number(usd || 0)
  if (!amountUsd) return '—'
  if (currency === 'INR') {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: 'INR',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amountUsd * inrRate)
  }
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(amountUsd)
}
