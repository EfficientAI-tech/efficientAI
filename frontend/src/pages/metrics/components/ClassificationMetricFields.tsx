import { Plus, Trash2 } from 'lucide-react'
import type { ClassificationFormState } from '../classificationMetricUtils'

const INPUT_CLASS =
  'block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:ring-primary-500'
const TEXTAREA_CLASS = `${INPUT_CLASS} resize-y min-h-[72px]`

type Props = {
  form: ClassificationFormState
  onChange: (next: ClassificationFormState) => void
  showScope?: boolean
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <label className="inline-flex items-center gap-2 cursor-pointer select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
      />
      <span className="text-sm font-medium text-gray-900">{label}</span>
    </label>
  )
}

export default function ClassificationMetricFields({
  form,
  onChange,
  showScope = true,
}: Props) {
  const patch = (partial: Partial<ClassificationFormState>) =>
    onChange({ ...form, ...partial })

  return (
    <div className="space-y-5">
      <p className="text-sm text-gray-600">
        Configure Jev classification questions (Noul, Choice, Score). Evaluations
        require a Jev model (for example typesafe/jev-1.13.0) and use the
        transcript source selected when you run the evaluation.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5">
        <div className="md:col-span-2">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Metric name *
          </label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => patch({ name: e.target.value })}
            placeholder="e.g. Call outcome classification"
            className={INPUT_CLASS}
          />
        </div>

        <div className="md:col-span-2">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Description (optional)
          </label>
          <textarea
            value={form.description}
            onChange={(e) => patch({ description: e.target.value })}
            rows={2}
            placeholder="Short note for your team — not sent as Jev instructions"
            className={TEXTAREA_CLASS}
          />
        </div>
      </div>

      {/* Noul */}
      <div className="rounded-xl border border-gray-200 p-4 space-y-3">
        <Toggle
          label="Noul (yes/no probability)"
          checked={form.noul.enabled}
          onChange={(enabled) =>
            patch({ noul: { ...form.noul, enabled } })
          }
        />
        {form.noul.enabled && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Instructions
              </label>
              <textarea
                value={form.noul.instructions}
                onChange={(e) =>
                  patch({ noul: { ...form.noul, instructions: e.target.value } })
                }
                rows={2}
                className={TEXTAREA_CLASS}
                placeholder="Was the support issue resolved?"
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Criteria — true
                </label>
                <textarea
                  value={form.noul.trueCriteria}
                  onChange={(e) =>
                    patch({ noul: { ...form.noul, trueCriteria: e.target.value } })
                  }
                  rows={2}
                  className={TEXTAREA_CLASS}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Criteria — false
                </label>
                <textarea
                  value={form.noul.falseCriteria}
                  onChange={(e) =>
                    patch({ noul: { ...form.noul, falseCriteria: e.target.value } })
                  }
                  rows={2}
                  className={TEXTAREA_CLASS}
                />
              </div>
            </div>
          </>
        )}
      </div>

      {/* Choice */}
      <div className="rounded-xl border border-gray-200 p-4 space-y-3">
        <Toggle
          label="Choice (one option + distribution)"
          checked={form.choice.enabled}
          onChange={(enabled) =>
            patch({ choice: { ...form.choice, enabled } })
          }
        />
        {form.choice.enabled && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Instructions
              </label>
              <textarea
                value={form.choice.instructions}
                onChange={(e) =>
                  patch({ choice: { ...form.choice, instructions: e.target.value } })
                }
                rows={2}
                className={TEXTAREA_CLASS}
              />
            </div>
            <div className="space-y-2">
              <span className="text-xs font-medium text-gray-700">Options</span>
              {form.choice.options.map((opt, idx) => (
                <div
                  key={opt.local_id}
                  className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-2 items-start"
                >
                  <input
                    type="text"
                    value={opt.label}
                    onChange={(e) => {
                      const options = form.choice.options.map((o, i) =>
                        i === idx ? { ...o, label: e.target.value } : o,
                      )
                      patch({ choice: { ...form.choice, options } })
                    }}
                    placeholder="Option label"
                    className={INPUT_CLASS}
                  />
                  <input
                    type="text"
                    value={opt.description}
                    onChange={(e) => {
                      const options = form.choice.options.map((o, i) =>
                        i === idx ? { ...o, description: e.target.value } : o,
                      )
                      patch({ choice: { ...form.choice, options } })
                    }}
                    placeholder="When this option applies"
                    className={INPUT_CLASS}
                  />
                  <button
                    type="button"
                    disabled={form.choice.options.length <= 2}
                    onClick={() => {
                      const options = form.choice.options.filter((_, i) => i !== idx)
                      patch({ choice: { ...form.choice, options } })
                    }}
                    className="p-2 text-gray-400 hover:text-red-600 disabled:opacity-30"
                    aria-label="Remove option"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() =>
                  patch({
                    choice: {
                      ...form.choice,
                      options: [
                        ...form.choice.options,
                        {
                          local_id: `opt-${Date.now()}`,
                          label: '',
                          description: '',
                        },
                      ],
                    },
                  })
                }
                className="inline-flex items-center gap-1 text-sm font-medium text-primary-600 hover:text-primary-700"
              >
                <Plus className="h-4 w-4" />
                Add option
              </button>
            </div>
          </>
        )}
      </div>

      {/* Score */}
      <div className="rounded-xl border border-gray-200 p-4 space-y-3">
        <Toggle
          label="Score (ordered levels)"
          checked={form.score.enabled}
          onChange={(enabled) =>
            patch({ score: { ...form.score, enabled } })
          }
        />
        {form.score.enabled && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Instructions
              </label>
              <textarea
                value={form.score.instructions}
                onChange={(e) =>
                  patch({ score: { ...form.score, instructions: e.target.value } })
                }
                rows={2}
                className={TEXTAREA_CLASS}
              />
            </div>
            <div className="space-y-2">
              <span className="text-xs font-medium text-gray-700">
                Levels (low → high)
              </span>
              {form.score.levels.map((level, idx) => (
                <div key={`level-${idx}`} className="flex gap-2 items-center">
                  <span className="text-xs text-gray-400 w-6">{idx + 1}.</span>
                  <input
                    type="text"
                    value={level}
                    onChange={(e) => {
                      const levels = form.score.levels.map((l, i) =>
                        i === idx ? e.target.value : l,
                      )
                      patch({ score: { ...form.score, levels } })
                    }}
                    className={INPUT_CLASS}
                  />
                  <button
                    type="button"
                    disabled={form.score.levels.length <= 2}
                    onClick={() => {
                      const levels = form.score.levels.filter((_, i) => i !== idx)
                      patch({ score: { ...form.score, levels } })
                    }}
                    className="p-2 text-gray-400 hover:text-red-600 disabled:opacity-30"
                    aria-label="Remove level"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() =>
                  patch({
                    score: {
                      ...form.score,
                      levels: [...form.score.levels, ''],
                    },
                  })
                }
                className="inline-flex items-center gap-1 text-sm font-medium text-primary-600 hover:text-primary-700"
              >
                <Plus className="h-4 w-4" />
                Add level
              </button>
            </div>
          </>
        )}
      </div>

      {showScope && (
        <div className="border border-gray-200 rounded-lg p-4 space-y-3">
          <p className="text-sm font-medium text-gray-900">Visibility scope</p>
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              name="classification-scope"
              checked={form.scope === 'workspace'}
              onChange={() => patch({ scope: 'workspace' })}
              className="mt-0.5"
            />
            <span className="text-sm text-gray-800">This workspace only</span>
          </label>
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              name="classification-scope"
              checked={form.scope === 'organization'}
              onChange={() => patch({ scope: 'organization' })}
              className="mt-0.5"
            />
            <span className="text-sm text-gray-800">
              All workspaces in this organization
            </span>
          </label>
        </div>
      )}

      <div className="flex items-center">
        <input
          type="checkbox"
          id="classification-enabled"
          checked={form.enabled}
          onChange={(e) => patch({ enabled: e.target.checked })}
          className="h-4 w-4 rounded border-gray-300 text-primary-600"
        />
        <label htmlFor="classification-enabled" className="ml-2 text-sm text-gray-900">
          Enable this metric
        </label>
      </div>
    </div>
  )
}
