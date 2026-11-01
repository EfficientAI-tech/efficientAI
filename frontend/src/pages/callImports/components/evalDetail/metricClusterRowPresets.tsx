const METRIC_CLUSTER_ROW_PRESETS = [25, 50, 500] as const
export type MetricClusterRowPreset =
  (typeof METRIC_CLUSTER_ROW_PRESETS)[number] | 'all'

function metricClusterSelectedCount(
  totalEligible: number,
  preset: MetricClusterRowPreset,
): number {
  if (totalEligible <= 0) return 0
  if (preset === 'all') return totalEligible
  return Math.min(preset, totalEligible)
}

function MetricClusterRowPicker({
  totalEligible,
  preset,
  onChangePreset,
  disabled,
}: {
  totalEligible: number
  preset: MetricClusterRowPreset
  onChangePreset: (next: MetricClusterRowPreset) => void
  disabled?: boolean
}) {
  const selectedCount = metricClusterSelectedCount(totalEligible, preset)

  const presetActive = (n: number) =>
    preset !== 'all' && preset === n && selectedCount === n

  const allActive = preset === 'all' && totalEligible > 0

  const presetButtonClass = (active: boolean) =>
    'rounded-full px-2 py-0.5 border text-[10px] font-medium transition-colors disabled:opacity-40 ' +
    (active
      ? 'border-primary-300 bg-primary-50 text-primary-800'
      : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50')

  return (
    <div className="rounded-md border border-gray-200 bg-white">
      <div className="px-3 py-3 border-b border-gray-100 bg-gray-50/80 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-medium text-gray-700">
            Calls to include ({selectedCount} / {totalEligible} eligible)
          </p>
        </div>
        {totalEligible > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {METRIC_CLUSTER_ROW_PRESETS.map((n) => (
              <button
                key={n}
                type="button"
                disabled={disabled}
                className={presetButtonClass(presetActive(n))}
                onClick={() => onChangePreset(n)}
              >
                First {n}
              </button>
            ))}
            <button
              type="button"
              disabled={disabled}
              className={presetButtonClass(allActive)}
              onClick={() => onChangePreset('all')}
            >
              All {totalEligible}
            </button>
          </div>
        ) : (
          <p className="text-xs text-gray-500">
            No completed calls with a flagged quality metric yet.
          </p>
        )}
      </div>
    </div>
  )
}

export {
  METRIC_CLUSTER_ROW_PRESETS,
  metricClusterSelectedCount,
  MetricClusterRowPicker,
}
