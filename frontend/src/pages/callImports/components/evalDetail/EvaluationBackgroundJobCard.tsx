import { Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import Button from '../../../../components/Button'
import type { JobProgressView } from './evaluationJobProgress'

function EvaluationBackgroundJobCard({
  title,
  progress,
  onStop,
  stopLoading,
  stopDisabled,
  footer,
}: {
  title: string
  progress: JobProgressView
  onStop?: () => void
  stopLoading?: boolean
  stopDisabled?: boolean
  footer?: ReactNode
}) {
  const { phaseLabel, statsLine, metaLine, pct, indeterminate } = progress

  return (
    <section className="rounded-lg border border-amber-200/90 bg-gradient-to-b from-amber-50/80 to-white px-3 py-2.5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <Loader2
              className="h-3.5 w-3.5 shrink-0 animate-spin text-amber-600"
              aria-hidden
            />
            <p className="text-xs font-semibold text-gray-900 truncate">{title}</p>
            {!indeterminate ? (
              <span className="text-[10px] font-medium text-amber-800/90 tabular-nums shrink-0">
                {pct}%
              </span>
            ) : null}
          </div>
          <p className="text-[11px] text-amber-950/85 leading-snug">{phaseLabel}</p>
          {(statsLine || metaLine) && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-gray-600 tabular-nums">
              {statsLine ? <span>{statsLine}</span> : null}
              {metaLine ? (
                <span className="text-gray-500 truncate max-w-full">{metaLine}</span>
              ) : null}
            </div>
          )}
          <div
            className="h-2 w-full rounded-full bg-amber-100 overflow-hidden"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={indeterminate ? undefined : pct}
            aria-label={phaseLabel}
          >
            {indeterminate ? (
              <div className="h-full w-[38%] bg-amber-500/90 animate-pulse rounded-full" />
            ) : (
              <div
                className="h-full bg-amber-600 transition-[width] duration-500 ease-out rounded-full"
                style={{ width: `${Math.min(100, Math.max(pct, pct > 0 ? 6 : 0))}%` }}
              />
            )}
          </div>
          {footer}
        </div>
        {onStop ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onStop}
            isLoading={stopLoading}
            disabled={stopDisabled || stopLoading}
            className="shrink-0 h-8 min-h-8 px-2.5 text-[11px] font-medium text-amber-900 border-amber-200/90 bg-white/80 hover:bg-amber-50"
          >
            Stop
          </Button>
        ) : null}
      </div>
    </section>
  )
}

export { EvaluationBackgroundJobCard }
