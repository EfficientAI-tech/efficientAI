import type { LucideIcon } from 'lucide-react'
import { Check } from 'lucide-react'

interface WizardIconCardProps {
  label: string
  icon: LucideIcon
  selected: boolean
  onSelect: () => void
  /** Primary medium pickers (Voice Agent vs Chat Agent). */
  medium?: boolean
  /** Wider tiles for secondary choices (e.g. telephony vs platform). */
  large?: boolean
}

export default function WizardIconCard({
  label,
  icon: Icon,
  selected,
  onSelect,
  medium = false,
  large = false,
}: WizardIconCardProps) {
  const sizeClass = large
    ? 'min-h-[9.5rem] px-5 py-7 gap-3'
    : medium
      ? 'min-h-[8.25rem] px-5 py-6 gap-2.5'
      : 'min-h-[8rem] px-4 py-5 gap-2.5'

  const iconClass = large ? 'h-8 w-8' : medium ? 'h-7 w-7' : 'h-7 w-7'
  const textClass = large ? 'text-sm' : 'text-sm'

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
        className={`text-center leading-snug font-semibold px-1 ${textClass} ${
          selected ? 'text-primary-900' : 'text-gray-800'
        }`}
      >
        {label}
      </span>
    </button>
  )
}
