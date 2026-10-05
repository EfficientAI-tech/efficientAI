import type { LucideIcon } from 'lucide-react'
import { Check } from 'lucide-react'

interface WizardIconCardProps {
  label: string
  icon: LucideIcon
  selected: boolean
  onSelect: () => void
  /** One-line hint under the label. */
  subtitle?: string
  /** Primary medium pickers (Voice Agent vs Chat Agent). */
  medium?: boolean
  /** Wider tiles for secondary choices (e.g. telephony vs platform). */
  large?: boolean
  /** Compact tiles for short entry screens in a small modal. */
  compact?: boolean
}

export default function WizardIconCard({
  label,
  icon: Icon,
  selected,
  onSelect,
  subtitle,
  medium = false,
  large = false,
  compact = false,
}: WizardIconCardProps) {
  const sizeClass = compact
    ? 'min-h-[8rem] px-4 py-5 gap-3'
    : large
      ? 'min-h-[9.5rem] px-5 py-7 gap-3'
      : medium
        ? 'min-h-[8.25rem] px-5 py-6 gap-2.5'
        : 'min-h-[8rem] px-4 py-5 gap-2.5'

  const iconClass = compact ? 'h-8 w-8' : large ? 'h-8 w-8' : medium ? 'h-7 w-7' : 'h-7 w-7'
  const labelClass = compact
    ? 'text-sm sm:text-base'
    : large
      ? 'text-sm'
      : 'text-sm'

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`relative flex flex-col items-center justify-center rounded-xl border-2 transition-colors ${sizeClass} ${
        selected
          ? 'border-primary-600 bg-primary-50 ring-1 ring-primary-200 shadow-sm'
          : 'border-gray-200 bg-white hover:border-primary-200 hover:bg-primary-50/30'
      }`}
    >
      {selected ? (
        <span
          className="absolute top-2.5 right-2.5 flex h-5 w-5 items-center justify-center rounded-full bg-primary-600 text-white"
          aria-hidden
        >
          <Check className="h-3 w-3 stroke-[3]" />
        </span>
      ) : null}
      <Icon
        className={`${iconClass} ${selected ? 'text-primary-700' : 'text-gray-600'}`}
        strokeWidth={1.5}
      />
      <span
        className={`text-center leading-snug font-semibold px-1 ${labelClass} ${
          selected ? 'text-primary-900' : 'text-gray-800'
        }`}
      >
        {label}
      </span>
      {subtitle ? (
        <span
          className={`text-center text-gray-500 px-2 line-clamp-2 ${
            compact ? 'text-[11px] sm:text-xs leading-snug' : 'text-[11px] leading-tight'
          }`}
        >
          {subtitle}
        </span>
      ) : null}
    </button>
  )
}
