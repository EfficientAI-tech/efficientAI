import { HelpCircle } from 'lucide-react'
import { clsx } from 'clsx'
import { useWalkthrough } from '../../context/WalkthroughContext'

interface WalkthroughToggleButtonProps {
  className?: string
}

export default function WalkthroughToggleButton({
  className,
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
        'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-300 z-[10040]',
        isCollapsed
          ? 'border-amber-300 bg-white text-amber-700 hover:bg-amber-50'
          : 'border-amber-500 bg-amber-500 text-white hover:border-amber-600 hover:bg-amber-600',
        className
      )}
      aria-label={isCollapsed ? 'Show how to guide' : 'Hide how to guide'}
      aria-expanded={!isCollapsed}
      title={isCollapsed ? 'Show how to guide' : 'Hide how to guide'}
    >
      <HelpCircle className="h-4 w-4" />
    </button>
  )
}
