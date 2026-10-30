import { isReliable } from './metricMath'

export default function SampleSizeBadge({ count }: { count: number }) {
  const reliable = isReliable(count)
  return (
    <span
      className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium tabular-nums ${
        reliable ? 'bg-gray-100 text-gray-600' : 'bg-amber-50 text-amber-700'
      }`}
      title={reliable ? `${count} scored runs` : `Only ${count} scored runs — not enough to judge a trend`}
    >
      n={count}
    </span>
  )
}
