import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'

export interface SortableHeaderProps {
  columnKey: string
  activeKey: string | null
  activeDir: 'asc' | 'desc'
  title?: string
  onCycle: (key: string) => void
  className?: string
  rightSlot?: React.ReactNode
  children: React.ReactNode
}

export function SortableHeader({
  columnKey,
  activeKey,
  activeDir,
  title,
  onCycle,
  className,
  rightSlot,
  children,
}: SortableHeaderProps) {
  const isActive = activeKey === columnKey
  const Icon = !isActive
    ? ArrowUpDown
    : activeDir === 'asc'
      ? ArrowUp
      : ArrowDown
  const ariaSort = !isActive
    ? 'none'
    : activeDir === 'asc'
      ? 'ascending'
      : 'descending'
  return (
    <th
      aria-sort={ariaSort}
      className={
        'px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap ' +
        (className || '')
      }
    >
      <div className="inline-flex items-center gap-1">
        <button
          type="button"
          onClick={() => onCycle(columnKey)}
          title={title || (typeof children === 'string' ? children : undefined)}
          className={
            'inline-flex items-start gap-1 rounded px-1 -mx-1 py-0.5 hover:bg-gray-100 transition-colors ' +
            (isActive ? 'text-gray-900' : 'text-gray-500')
          }
        >
          <span className="min-w-0">{children}</span>
          <Icon
            className={
              'h-3 w-3 flex-shrink-0 mt-0.5 ' +
              (isActive ? 'text-primary-600' : 'text-gray-300')
            }
          />
        </button>
        {rightSlot}
      </div>
    </th>
  )
}
