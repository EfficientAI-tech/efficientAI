interface MetricCardProps {
  label: string
  valueA: number | null | undefined
  valueB: number | null | undefined
  unit?: string
  higherIsBetter?: boolean
}

export default function MetricCard({
  label,
  valueA,
  valueB,
  unit = '',
  higherIsBetter = true,
}: MetricCardProps) {
  const aVal = valueA ?? null
  const bVal = valueB ?? null
  const isSingleProvider = bVal === null
  const aWins = aVal !== null && bVal !== null && (higherIsBetter ? aVal > bVal : aVal < bVal)
  const bWins = aVal !== null && bVal !== null && (higherIsBetter ? bVal > aVal : bVal < aVal)

  const formatValue = (value: number | null): string => {
    if (value === null) return '—'
    const abs = Math.abs(value)
    const maximumFractionDigits =
      unit === 'ms'
        ? 1
        : abs >= 100
          ? 1
          : abs >= 10
            ? 2
            : 3
    const pretty = value.toLocaleString(undefined, { maximumFractionDigits })
    return `${pretty}${unit || ''}`
  }

  const aDisplay = formatValue(aVal)
  const bDisplay = formatValue(bVal)

  return (
    <div className="min-w-0 overflow-hidden bg-white rounded-lg p-4 border border-gray-100 shadow-sm">
      <p className="text-xs text-gray-500 mb-2 font-medium truncate">{label}</p>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 min-w-0">
        <span
          className={`min-w-0 truncate text-base lg:text-lg leading-tight font-bold tabular-nums ${aWins ? 'text-blue-600' : 'text-gray-700'}`}
          title={aDisplay}
        >
          {aDisplay}
        </span>
        {!isSingleProvider && (
          <>
            <span className="text-xs text-gray-400">vs</span>
            <span
              className={`min-w-0 truncate text-base lg:text-lg leading-tight font-bold tabular-nums ${bWins ? 'text-purple-600' : 'text-gray-700'}`}
              title={bDisplay}
            >
              {bDisplay}
            </span>
          </>
        )}
      </div>
    </div>
  )
}
