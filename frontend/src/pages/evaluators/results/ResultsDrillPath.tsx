import { ChevronRight } from 'lucide-react'

export type ResultsDrillCrumb = {
  label: string
  onClick?: () => void
}

type ResultsDrillPathProps = {
  crumbs: ResultsDrillCrumb[]
  levelLabel?: string
}

export default function ResultsDrillPath({ crumbs, levelLabel }: ResultsDrillPathProps) {
  if (crumbs.length <= 1 && !levelLabel) return null

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-gray-100 bg-gray-50/80 px-3 py-2">
      <nav className="flex flex-wrap items-center gap-1 text-sm min-w-0" aria-label="Filter path">
        {crumbs.map((crumb, index) => (
          <span key={`${crumb.label}-${index}`} className="flex items-center gap-1 min-w-0">
            {index > 0 ? <ChevronRight className="h-3.5 w-3.5 shrink-0 text-gray-400" /> : null}
            {crumb.onClick ? (
              <button
                type="button"
                onClick={crumb.onClick}
                className="truncate max-w-[14rem] font-medium text-primary-600 hover:text-primary-800"
              >
                {crumb.label}
              </button>
            ) : (
              <span className="font-semibold text-gray-900 truncate max-w-[14rem]">{crumb.label}</span>
            )}
          </span>
        ))}
      </nav>
      {levelLabel ? <p className="text-xs text-gray-500 shrink-0">{levelLabel}</p> : null}
    </div>
  )
}
