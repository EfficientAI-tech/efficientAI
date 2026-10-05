import {
  ALL_SURFACES,
  METRIC_SURFACE_LABELS,
  type MetricSurface,
} from '../../lib/metricSurfaces'

type Props = {
  supported: MetricSurface[]
  enabled: MetricSurface[]
  onChange: (next: { supported: MetricSurface[]; enabled: MetricSurface[] }) => void
  compact?: boolean
}

export default function MetricSurfacesField({
  supported,
  enabled,
  onChange,
  compact = false,
}: Props) {
  const toggle = (surface: MetricSurface, checked: boolean) => {
    const nextSupported = checked
      ? [...new Set([...supported, surface])]
      : supported.filter((s) => s !== surface)
    const nextEnabled = checked
      ? [...new Set([...enabled, surface])]
      : enabled.filter((s) => nextSupported.includes(s))
    onChange({ supported: nextSupported, enabled: nextEnabled })
  }

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">Surfaces</label>
      <div className={`flex flex-wrap gap-2 ${compact ? '' : 'gap-3'}`}>
        {ALL_SURFACES.map((surface) => {
          const checked = supported.includes(surface)
          const isOn = enabled.includes(surface)
          return (
            <label
              key={surface}
              className={`inline-flex items-center gap-2 text-sm cursor-pointer rounded-lg border px-3 py-2 transition ${
                checked && isOn
                  ? 'border-primary-300 bg-primary-50 text-primary-800'
                  : checked
                    ? 'border-gray-300 bg-white text-gray-700'
                    : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => toggle(surface, e.target.checked)}
                className="h-4 w-4 text-primary-600 border-gray-300 rounded"
              />
              {METRIC_SURFACE_LABELS[surface]}
            </label>
          )
        })}
      </div>
      {!compact ? (
        <p className="mt-1.5 text-xs text-gray-500">
          Voice agent and Chat agent use the eval transcript. Voice Playground uses audio where
          applicable.
        </p>
      ) : null}
    </div>
  )
}
