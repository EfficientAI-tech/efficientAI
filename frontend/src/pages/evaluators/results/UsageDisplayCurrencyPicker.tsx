import {
  getUsageDisplayCurrency,
  setUsageDisplayCurrency,
  type UsageDisplayCurrency,
} from '../../../lib/usageCurrency'

export function UsageDisplayCurrencyPicker({
  value,
  onChange,
  className = '',
  compact = false,
}: {
  value: UsageDisplayCurrency
  onChange: (next: UsageDisplayCurrency) => void
  className?: string
  /** Menu style (block labels) vs inline pills */
  compact?: boolean
}) {
  const pick = (currency: UsageDisplayCurrency) => {
    setUsageDisplayCurrency(currency)
    onChange(currency)
  }

  if (compact) {
    return (
      <div className={`flex gap-0.5 rounded-lg border border-gray-200 bg-gray-50 p-0.5 ${className}`}>
        {(['USD', 'INR'] as const).map((currency) => (
          <button
            key={currency}
            type="button"
            onClick={() => pick(currency)}
            className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${value === currency
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-800'
              }`}
          >
            {currency}
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className={className}>
      <p className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-gray-400">Spend in</p>
      {(['USD', 'INR'] as const).map((currency) => (
        <button
          key={currency}
          type="button"
          onClick={() => pick(currency)}
          className={`block w-full px-3 py-1.5 text-left text-xs ${value === currency ? 'font-semibold text-gray-900' : 'text-gray-600 hover:bg-gray-50'
            }`}
        >
          {currency}
        </button>
      ))}
    </div>
  )
}

export function readUsageDisplayCurrency(): UsageDisplayCurrency {
  return getUsageDisplayCurrency()
}