import ParamSlider from '../agents/components/ParamSlider'

export interface PersonaBehaviorValues {
  llm_temperature?: number | null
  llm_max_tokens?: number | null
  response_delay_ms?: number | null
  max_turns?: number | null
  allow_interruptions?: boolean | null
}

interface PersonaBehaviorPanelProps {
  value: PersonaBehaviorValues
  onChange: (next: PersonaBehaviorValues) => void
  disabled?: boolean
  embedded?: boolean
}

export default function PersonaBehaviorPanel({
  value,
  onChange,
  disabled = false,
  embedded = false,
}: PersonaBehaviorPanelProps) {
  const inner = (
    <>
      {!embedded ? (
        <p className="text-xs font-semibold uppercase tracking-wide text-indigo-700">Caller behavior</p>
      ) : null}
      <ParamSlider
        label="Creativity (LLM temperature)"
        min={0}
        max={2}
        step={0.1}
        disabled={disabled}
        value={value.llm_temperature ?? null}
        onChange={(llm_temperature) => onChange({ ...value, llm_temperature })}
        helpText="Higher values produce more varied caller responses."
      />
      <ParamSlider
        label="Verbosity (max tokens)"
        min={1}
        max={8192}
        step={1}
        integer
        disabled={disabled}
        value={value.llm_max_tokens ?? null}
        onChange={(llm_max_tokens) => onChange({ ...value, llm_max_tokens })}
        helpText="Caps how long each caller reply can be."
      />
      <ParamSlider
        label="Patience (response delay ms)"
        min={0}
        max={10000}
        step={100}
        integer
        disabled={disabled}
        value={value.response_delay_ms ?? null}
        onChange={(response_delay_ms) => onChange({ ...value, response_delay_ms })}
        helpText="Wait time before the caller speaks after the agent finishes."
      />
      <ParamSlider
        label="Max turns"
        min={1}
        max={100}
        step={1}
        integer
        disabled={disabled}
        value={value.max_turns ?? null}
        onChange={(max_turns) => onChange({ ...value, max_turns })}
        helpText="Conversation length before the caller wraps up."
      />
      <label className="flex items-center justify-between gap-3 text-sm">
        <div>
          <span className="font-medium text-gray-800">Allow interruptions</span>
          <p className="text-xs text-gray-500 mt-0.5">
            Let the caller respond while the agent is still speaking.
          </p>
        </div>
        <input
          type="checkbox"
          disabled={disabled}
          checked={Boolean(value.allow_interruptions)}
          onChange={(e) =>
            onChange({ ...value, allow_interruptions: e.target.checked ? true : null })
          }
          className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
        />
      </label>
    </>
  )

  if (embedded) {
    return <div className="space-y-4">{inner}</div>
  }

  return (
    <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 p-4 space-y-4">
      {inner}
    </div>
  )
}
