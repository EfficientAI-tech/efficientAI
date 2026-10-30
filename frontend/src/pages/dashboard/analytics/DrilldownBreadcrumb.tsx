export default function DrilldownBreadcrumb({
  items,
}: {
  items: Array<{ label: string; onClick?: () => void }>
}) {
  return (
    <nav className="flex flex-wrap items-center gap-1 text-sm text-gray-500">
      {items.map((item, index) => (
        <span key={`${item.label}-${index}`} className="inline-flex items-center gap-1">
          {index > 0 && <span aria-hidden>/</span>}
          {item.onClick ? (
            <button type="button" onClick={item.onClick} className="hover:text-gray-900 underline-offset-2 hover:underline">
              {item.label}
            </button>
          ) : (
            <span className="font-medium text-gray-900">{item.label}</span>
          )}
        </span>
      ))}
    </nav>
  )
}
