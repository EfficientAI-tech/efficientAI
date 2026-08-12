import { ChevronRight } from 'lucide-react'
import { usageTheme } from './usageTheme'

type DrillCrumb = {
  label: string
  onClick?: () => void
}

type UsageDrillPathProps = {
  crumbs: DrillCrumb[]
  levelLabel: string
}

export default function UsageDrillPath({ crumbs, levelLabel }: UsageDrillPathProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <nav className="flex flex-wrap items-center gap-1 text-sm min-w-0">
        {crumbs.map((crumb, i) => (
          <span key={i} className="flex items-center gap-1 min-w-0">
            {i > 0 ? <ChevronRight className="h-3.5 w-3.5 shrink-0 text-gray-400" /> : null}
            {crumb.onClick ? (
              <button
                type="button"
                onClick={crumb.onClick}
                className={`truncate max-w-[14rem] ${usageTheme.linkStrong}`}
              >
                {crumb.label}
              </button>
            ) : (
              <span className="font-semibold text-gray-900 truncate max-w-[14rem]">
                {crumb.label}
              </span>
            )}
          </span>
        ))}
      </nav>
      <p className="text-xs text-gray-500 shrink-0">{levelLabel}</p>
    </div>
  )
}
