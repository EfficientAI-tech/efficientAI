import type { ReactNode } from 'react'
import { HelpCircle } from 'lucide-react'

type InfoTooltipProps = {
  title: string
  children: ReactNode
  className?: string
  placement?: 'top' | 'bottom'
  /** Horizontal anchor; use 'start' near a container's left edge to avoid clipping. */
  align?: 'center' | 'start'
  /** Tailwind width class for the popover body. */
  widthClassName?: string
}

/** Hover/focus help icon with a dark popover. Pure CSS — no portal or state. */
export default function InfoTooltip({
  title,
  children,
  className = '',
  placement = 'top',
  align = 'center',
  widthClassName = 'w-64',
}: InfoTooltipProps) {
  const placementClass = placement === 'top' ? 'bottom-full mb-2' : 'top-full mt-2'
  const alignClass = align === 'center' ? 'left-1/2 -translate-x-1/2' : '-left-2'
  return (
    <span className={`relative inline-flex group ${className}`}>
      <button
        type="button"
        aria-label={title}
        onClick={(e) => e.preventDefault()}
        className="inline-flex rounded-full text-gray-400 hover:text-gray-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 cursor-help"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>
      <span
        role="tooltip"
        className={`pointer-events-none absolute z-30 ${alignClass} ${placementClass} ${widthClassName} rounded-md bg-gray-900 px-3 py-2 text-left text-xs font-normal leading-snug text-white opacity-0 shadow-lg transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100`}
      >
        <span className="block text-[11px] font-semibold uppercase tracking-wide text-yellow-300">
          {title}
        </span>
        <span className="mt-1 block text-gray-100">{children}</span>
      </span>
    </span>
  )
}
