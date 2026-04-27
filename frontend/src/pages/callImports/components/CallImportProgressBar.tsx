interface CallImportProgressBarProps {
  total: number
  completed: number
  failed: number
  showLabel?: boolean
}

export default function CallImportProgressBar({
  total,
  completed,
  failed,
  showLabel = true,
}: CallImportProgressBarProps) {
  const safeTotal = Math.max(total, 0)
  const completedPct = safeTotal > 0 ? (completed / safeTotal) * 100 : 0
  const failedPct = safeTotal > 0 ? (failed / safeTotal) * 100 : 0

  return (
    <div className="w-full">
      <div
        className="w-full h-2 bg-gray-200 rounded-full overflow-hidden flex"
        role="progressbar"
        aria-valuenow={completed + failed}
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
          <span className="text-green-700 font-medium">{completed}</span>
          <span className="text-gray-400">/</span>
          <span>{safeTotal}</span>
          {failed > 0 && (
            <span className="ml-2 text-red-700 font-medium">{failed} failed</span>
          )}
        </div>
      )}
    </div>
  )
}
