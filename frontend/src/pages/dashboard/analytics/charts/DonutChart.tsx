const PALETTE = ['#10b981', '#6366f1', '#f97316', '#14b8a6', '#eab308', '#f43f5e', '#8b5cf6']

export default function DonutChart({
  segments,
  title,
  onSelect,
}: {
  segments: Array<{ label: string; count: number }>
  title?: string
  onSelect?: (label: string) => void
}) {
  const total = segments.reduce((sum, item) => sum + item.count, 0) || 1
  let acc = 0
  const stops = segments.map((item, index) => {
    const start = (acc / total) * 100
    acc += item.count
    const end = (acc / total) * 100
    return `${PALETTE[index % PALETTE.length]} ${start}% ${end}%`
  })

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      {title && <p className="text-sm font-medium text-gray-900 mb-2">{title}</p>}
      <div className="flex items-center gap-4">
        <div
          className="h-28 w-28 rounded-full"
          style={{ background: `conic-gradient(${stops.join(', ')})` }}
          aria-hidden
        >
          <div className="m-[18%] h-[64%] w-[64%] rounded-full bg-white" />
        </div>
        <ul className="flex-1 space-y-1 text-xs text-gray-600">
          {segments.map((item, index) => (
            <li key={item.label}>
              <button type="button" className="flex w-full items-center gap-1.5 hover:underline" onClick={() => onSelect?.(item.label)}>
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: PALETTE[index % PALETTE.length] }} />
                <span className="truncate">{item.label}</span>
                <span className="ml-auto tabular-nums">{item.count}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
