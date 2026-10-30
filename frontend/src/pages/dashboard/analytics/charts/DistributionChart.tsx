export default function DistributionChart({
  buckets,
  title,
}: {
  buckets: Array<{ x0: number; x1: number; count: number; label?: string }>
  title?: string
}) {
  const max = Math.max(...buckets.map((bucket) => bucket.count), 1)
  if (buckets.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-gray-200 bg-white px-4 py-8 text-sm text-gray-500">
        No distribution in this window.
      </div>
    )
  }
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      {title && <p className="text-sm font-medium text-gray-900 mb-2">{title}</p>}
      <div className="space-y-1.5">
        {buckets.map((bucket) => (
          <div key={bucket.label ?? `${bucket.x0}-${bucket.x1}`} className="flex items-center gap-2 text-xs text-gray-600">
            <span className="w-28 truncate tabular-nums">
              {bucket.label ?? `${bucket.x0.toFixed(1)}–${bucket.x1.toFixed(1)}`}
            </span>
            <div className="h-2.5 flex-1 rounded-full bg-gray-100">
              <div
                className="h-2.5 rounded-full bg-indigo-400"
                style={{ width: `${(bucket.count / max) * 100}%` }}
              />
            </div>
            <span className="w-8 text-right tabular-nums">{bucket.count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
