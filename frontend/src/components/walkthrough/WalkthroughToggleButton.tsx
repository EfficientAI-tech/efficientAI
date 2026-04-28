import { HelpCircle } from 'lucide-react'
import { clsx } from 'clsx'
import { useWalkthrough } from '../../context/WalkthroughContext'

interface WalkthroughToggleButtonProps {
  className?: string
  compact?: boolean
}

export default function WalkthroughToggleButton({
  className,
  compact = false,
}: WalkthroughToggleButtonProps) {
  const { activeDefinition, isCollapsed, toggleCollapsed } = useWalkthrough()

  if (!activeDefinition) {
    return null
  }

  return (
    <button
      type="button"
      onClick={toggleCollapsed}
      className={clsx(
        'inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-full border font-semibold shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-300',
        compact ? 'h-8 px-3 text-xs' : 'h-10 px-4 text-sm',
        isCollapsed
          ? 'border-amber-300 bg-white text-amber-700 hover:bg-amber-50'
          : 'border-amber-500 bg-amber-500 text-white hover:border-amber-600 hover:bg-amber-600',
        className
      )}
      aria-label={isCollapsed ? 'Show how to guide' : 'Hide how to guide'}
      aria-expanded={!isCollapsed}
      title={isCollapsed ? 'Show how to guide' : 'Hide how to guide'}
    >
      <HelpCircle className={compact ? 'h-3.5 w-3.5' : 'h-4 w-4'} />
      <span>How to</span>
    </button>
  )
}
