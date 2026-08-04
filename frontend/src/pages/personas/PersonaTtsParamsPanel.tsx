import ParamSlider from '../agents/components/ParamSlider'
import { getPersonaTtsParams, type PersonaParamDef } from './personaTtsParams'

interface PersonaTtsParamsPanelProps {
  provider?: string | null
  value: Record<string, unknown>
  onChange: (next: Record<string, unknown>) => void
  disabled?: boolean
  /** When true, omit outer card styling (for use inside persona tiles). */
  embedded?: boolean
}

function updateConfig(
  config: Record<string, unknown>,
  key: string,
  next: unknown,
): Record<string, unknown> {
  const copy = { ...config }
  if (next === null || next === undefined || next === '') {
    delete copy[key]
  } else {
    copy[key] = next
  }
  return copy
}

function renderParam(
  def: PersonaParamDef,
  config: Record<string, unknown>,
  onChange: (next: Record<string, unknown>) => void,
  disabled?: boolean,
) {
  const raw = config[def.key]

  if (def.kind === 'slider') {
    return (
      <ParamSlider
        key={def.key}
        label={def.label}
        min={def.min ?? 0}
        max={def.max ?? 1}
        step={def.step ?? 0.1}
        integer={def.integer}
        disabled={disabled}
        value={typeof raw === 'number' ? raw : null}
        onChange={(next) => onChange(updateConfig(config, def.key, next))}
        helpText={def.helpText}
      />
    )
  }

  if (def.kind === 'boolean') {
    return (
      <label key={def.key} className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium text-gray-800">{def.label}</span>
        <input
          type="checkbox"
          disabled={disabled}
          checked={Boolean(raw)}
          onChange={(e) => onChange(updateConfig(config, def.key, e.target.checked ? true : null))}
          className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
        />
      </label>
    )
  }

  if (def.kind === 'select') {
    return (
      <div key={def.key}>
        <label className="block text-xs font-medium text-gray-600 mb-1">{def.label}</label>
        <select
          disabled={disabled}
          value={typeof raw === 'string' ? raw : ''}
          onChange={(e) =>
            onChange(updateConfig(config, def.key, e.target.value || null))
          }
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500"
        >
          <option value="">Default</option>
          {(def.options ?? []).map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {def.helpText ? <p className="text-xs text-gray-500 mt-1">{def.helpText}</p> : null}
      </div>
    )
  }

  return (
    <div key={def.key}>
      <label className="block text-xs font-medium text-gray-600 mb-1">{def.label}</label>
      <input
        type="text"
        disabled={disabled}
        value={typeof raw === 'string' ? raw : ''}
        placeholder={def.placeholder}
        onChange={(e) => onChange(updateConfig(config, def.key, e.target.value || null))}
        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
      />
      {def.helpText ? <p className="text-xs text-gray-500 mt-1">{def.helpText}</p> : null}
    </div>
  )
}

export default function PersonaTtsParamsPanel({
  provider,
  value,
  onChange,
  disabled = false,
  embedded = false,
}: PersonaTtsParamsPanelProps) {
  const params = getPersonaTtsParams(provider)
  if (!provider || params.length === 0) {
    return (
      <p className="text-xs text-gray-500">
        Select a TTS provider on the Voice tab to configure synthesis options.
      </p>
    )
  }

  const inner = (
    <>
      {!embedded ? (
        <p className="text-xs font-semibold uppercase tracking-wide text-green-700">TTS settings</p>
      ) : null}
      {params.map((def) => renderParam(def, value, onChange, disabled))}
    </>
  )

  if (embedded) {
    return <div className="space-y-4">{inner}</div>
  }

  return (
    <div className="rounded-lg border border-green-100 bg-green-50/50 p-4 space-y-4">
      {inner}
    </div>
  )
}
