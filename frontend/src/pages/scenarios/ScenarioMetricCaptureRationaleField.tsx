import type { GeneratedScenarioMetricDraft } from './scenarioMetricWorkflowTypes'

type Props = {
  metricType: GeneratedScenarioMetricDraft['metric_type']
  checked: boolean
  disabled?: boolean
  onChange: (next: boolean) => void
}

export default function ScenarioMetricCaptureRationaleField({
  metricType,
  checked,
  disabled,
  onChange,
}: Props) {
  if (metricType === 'text') return null

  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50/70 p-3.5">
      <label className="flex items-start gap-2.5 cursor-pointer">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded disabled:opacity-60"
        />
        <span className="text-sm text-gray-800">
          <span className="font-medium">Capture LLM Rationale</span>
          <span className="block text-xs text-gray-500 mt-0.5">
            Ask the LLM to also return a 1-2 sentence reason alongside the value. Adds a{' '}
            <code className="px-1 py-0.5 bg-white border border-gray-200 rounded text-[11px]">
              &lt;Name&gt; - LLM Rationale
            </code>{' '}
            column to the call-import CSV export.
          </span>
        </span>
      </label>
    </div>
  )
}
