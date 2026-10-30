const PALETTE = ['#10b981', '#6366f1', '#f97316', '#14b8a6', '#eab308', '#f43f5e', '#8b5cf6']

export default function StackedShareChart({
  segments,
  title,
  onSelect,
}: {
  segments: Array<{ label: string; count: number }>
  title?: string
  onSelect?: (label: string) => void
}) {
  const total = segments.reduce((sum, item) => sum + item.count, 0) || 1
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      {title && <p className="text-sm font-medium text-gray-900 mb-2">{title}</p>}
      <div className="flex h-3 overflow-hidden rounded-full bg-gray-100">
        {segments.map((item, index) => (
          <button
            key={item.label}
            type="button"
            title={`${item.label}: ${item.count}`}
            onClick={() => onSelect?.(item.label)}
            className="h-full"
            style={{ width: `${(item.count / total) * 100}%`, backgroundColor: PALETTE[index % PALETTE.length] }}
          />
        ))}
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-gray-600">
        {segments.map((item, index) => (
          <li key={item.label} className="flex items-center gap-1.5">
            <span
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: PALETTE[index % PALETTE.length] }}
            />
            <button type="button" className="hover:underline" onClick={() => onSelect?.(item.label)}>
              {item.label}
            </button>
            <span className="ml-auto tabular-nums">{Math.round((item.count / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
