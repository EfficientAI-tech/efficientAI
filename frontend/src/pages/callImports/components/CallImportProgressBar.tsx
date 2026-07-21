interface CallImportProgressBarProps {
  total: number
  completed: number
  failed: number
  showLabel?: boolean
  deleting?: boolean
}

export default function CallImportProgressBar({
  total,
  completed,
  failed,
  showLabel = true,
  deleting = false,
}: CallImportProgressBarProps) {
  if (deleting) {
    return (
      <div className="w-full">
        <div
          className="w-full h-2 bg-gray-200 rounded-full overflow-hidden"
          role="progressbar"
          aria-busy="true"
          aria-label="Removing import"
        >
          <div className="h-full w-full bg-gray-400 animate-pulse" />
        </div>
        {showLabel && (
          <div className="mt-1 text-xs text-gray-500 italic">Removing…</div>
        )}
      </div>
    )
  }

  const safeTotal = Math.max(total, 0)
  const safeCompleted = safeTotal > 0 ? Math.min(completed, safeTotal) : Math.max(completed, 0)
  const safeFailed = safeTotal > 0 ? Math.min(failed, Math.max(safeTotal - safeCompleted, 0)) : Math.max(failed, 0)
  const completedPct = safeTotal > 0 ? (safeCompleted / safeTotal) * 100 : 0
  const failedPct = safeTotal > 0 ? (safeFailed / safeTotal) * 100 : 0

  return (
    <div className="w-full">
      <div
        className="w-full h-2 bg-gray-200 rounded-full overflow-hidden flex"
        role="progressbar"
        aria-valuenow={safeCompleted + safeFailed}
        aria-valuemin={0}
        aria-valuemax={safeTotal}
      >
        <div
          className="h-full bg-green-500 transition-all duration-300"
          style={{ width: `${completedPct}%` }}
        />
        <div
          className="h-full bg-red-500 transition-all duration-300"
          style={{ width: `${failedPct}%` }}
        />
      </div>
      {showLabel && (
        <div className="mt-1 text-xs text-gray-600 flex items-center gap-2">
          <span className="text-green-700 font-medium">{safeCompleted}</span>
          <span className="text-gray-400">/</span>
          <span>{safeTotal}</span>
          {safeFailed > 0 && (
            <span className="ml-2 text-red-700 font-medium">{safeFailed} failed</span>
          )}
        </div>
      )}
    </div>
  )
}
