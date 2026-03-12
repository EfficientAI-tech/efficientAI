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

  return (
    <div className="bg-white rounded-lg p-4 border border-gray-100 shadow-sm">
      <p className="text-xs text-gray-500 mb-2 font-medium">{label}</p>
      <div className="flex items-baseline gap-3">
        <span className={`text-lg font-bold ${aWins ? 'text-blue-600' : 'text-gray-700'}`}>
          {aVal !== null ? `${aVal}${unit || ''}` : '—'}
        </span>
        {!isSingleProvider && (
          <>
            <span className="text-xs text-gray-400">vs</span>
            <span className={`text-lg font-bold ${bWins ? 'text-purple-600' : 'text-gray-700'}`}>
              {bVal !== null ? `${bVal}${unit || ''}` : '—'}
            </span>
          </>
        )}
      </div>
    </div>
  )
}
