import { HelpCircle } from 'lucide-react'
import { clsx } from 'clsx'
import { useWalkthrough } from '../../context/WalkthroughContext'

interface WalkthroughToggleButtonProps {
  className?: string
}

export default function WalkthroughToggleButton({
  className,
}: WalkthroughToggleButtonProps) {
  const { activeDefinition, isCollapsed, setCollapsed } = useWalkthrough()

  if (!activeDefinition || !isCollapsed) {
    return null
  }

  return (
    <button
      type="button"
      onClick={() => setCollapsed(false)}
      className={clsx(
        'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-amber-300 bg-white text-amber-700 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:bg-amber-50 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-300 z-[10040]',
        className
      )}
      aria-label="Show how to guide"
      aria-expanded={false}
      title="Show how to guide"
    >
      <HelpCircle className="h-4 w-4" />
    </button>
  )
}
