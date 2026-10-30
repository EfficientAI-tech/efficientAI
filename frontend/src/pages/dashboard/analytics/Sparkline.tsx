const SIMULATION_COLOR = '#6366f1'
const LIVE_COLOR = '#14b8a6'

export default function Sparkline({
  values,
  width = 88,
  height = 28,
  source = 'simulation',
}: {
  values: Array<number | null>
  width?: number
  height?: number
  source?: 'simulation' | 'live'
}) {
  const numeric = values.filter((value): value is number => value != null)
  if (numeric.length < 2) {
    return <div className="text-[10px] text-gray-400">No trend yet</div>
  }
  const min = Math.min(...numeric)
  const max = Math.max(...numeric)
  const span = max - min || 1
  const step = values.length > 1 ? width / (values.length - 1) : width
  const points = values
    .map((value, index) => {
      if (value == null) return null
      const x = index * step
      const y = height - ((value - min) / span) * (height - 4) - 2
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .filter((point): point is string => point != null)
    .join(' ')

  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden>
      <polyline
        fill="none"
        stroke={source === 'live' ? LIVE_COLOR : SIMULATION_COLOR}
        strokeWidth="1.75"
        strokeLinejoin="round"
        strokeLinecap="round"
        points={points}
      />
    </svg>
  )
}

export { SIMULATION_COLOR, LIVE_COLOR }
