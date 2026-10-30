import { useState, type ReactNode } from 'react'
import { Info, Plus, Trash2 } from 'lucide-react'
import { colorizeJson } from '../../../lib/colorizeJson'

export type JevType = 'noul' | 'choice' | 'score'
export type JevStateSource = 'user' | 'agent' | 'both'

export interface JevChoiceRow {
  key: string
  description: string
}

export interface JevMetricFormValue {
  name: string
  question: string
  state_source: JevStateSource
  enable_noul: boolean
  enable_choice: boolean
  enable_score: boolean
  noul_true: string
  noul_false: string
  choices: JevChoiceRow[]
  include_other: boolean
  choice_confidence_threshold: number
  score_levels: string[]
  score_confidence_threshold: number
}

const INPUT_CLASS =
  'w-full rounded-lg border border-gray-200 bg-white px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 disabled:bg-gray-50 disabled:text-gray-500'

export function defaultJevForm(): JevMetricFormValue {
  return {
    name: '',
    question: '',
    state_source: 'both',
    enable_noul: true,
    enable_choice: false,
    enable_score: false,
    noul_true: '',
    noul_false: '',
    choices: [
      { key: '', description: '' },
      { key: '', description: '' },
    ],
    include_other: true,
    choice_confidence_threshold: 0.7,
    score_levels: ['', '', ''],
    score_confidence_threshold: 0.7,
  }
}

function readQuestionBlock(
  cfg: Record<string, unknown>,
  kind: JevType,
): Record<string, unknown> | null {
  const questions = cfg.questions
  if (questions && typeof questions === 'object' && !Array.isArray(questions)) {
    const block = (questions as Record<string, unknown>)[kind]
    if (block && typeof block === 'object' && !Array.isArray(block)) {
      return block as Record<string, unknown>
    }
  }
  if (cfg.jev_type === kind) {
    return cfg
  }
  return null
}

export function jevFormFromMetric(metric: {
  name: string
  description?: string | null
  custom_config?: Record<string, unknown> | null
}): JevMetricFormValue {
  const cfg = (metric.custom_config || {}) as Record<string, unknown>
  const form = defaultJevForm()
  form.name = metric.name
  form.question = metric.description || ''
  form.state_source = (cfg.state_source as JevStateSource) || 'both'

  const noul = readQuestionBlock(cfg, 'noul')
  const choice = readQuestionBlock(cfg, 'choice')
  const score = readQuestionBlock(cfg, 'score')
  form.enable_noul = Boolean(noul)
  form.enable_choice = Boolean(choice)
  form.enable_score = Boolean(score)
  if (!form.enable_noul && !form.enable_choice && !form.enable_score) {
    form.enable_noul = true
  }

  if (noul) {
    const criteria = noul.criteria
    if (criteria && typeof criteria === 'object' && !Array.isArray(criteria)) {
      const noulCriteria = criteria as Record<string, unknown>
      form.noul_true = String(noulCriteria.true ?? '')
      form.noul_false = String(noulCriteria.false ?? '')
    }
  }
  if (choice) {
    const criteria = choice.criteria
    if (criteria && typeof criteria === 'object' && !Array.isArray(criteria)) {
      const rows = Object.entries(criteria as Record<string, unknown>)
        .filter(([key]) => key.toLowerCase() !== 'other')
        .map(([key, value]) => ({
          key,
          description: value == null ? '' : String(value),
        }))
      form.choices = rows.length > 0 ? rows : form.choices
      form.include_other =
        Object.keys(criteria as Record<string, unknown>).some(
          (key) => key.toLowerCase() === 'other',
        ) || Boolean(choice.include_other)
    }
    if (typeof choice.confidence_threshold === 'number') {
      form.choice_confidence_threshold = choice.confidence_threshold
    }
  }
  if (score) {
    const criteria = score.criteria
    if (Array.isArray(criteria)) {
      const levels = criteria.map((level) => String(level ?? ''))
      form.score_levels = levels.length >= 2 ? levels : form.score_levels
    }
    if (typeof score.confidence_threshold === 'number') {
      form.score_confidence_threshold = score.confidence_threshold
    }
  }
  return form
}

export function jevFormToPayload(form: JevMetricFormValue) {
  const questions: Record<string, unknown> = {}
  if (form.enable_noul) {
    questions.noul = {
      criteria: {
        true: form.noul_true.trim() || 'What a yes means for this metric.',
        false: form.noul_false.trim() || 'What a no means for this metric.',
      },
    }
  }
  if (form.enable_choice) {
    questions.choice = {
      criteria: Object.fromEntries(
        form.choices
          .map((row) => [row.key.trim(), row.description.trim() || null] as const)
          .filter(([key]) => key.length > 0),
      ),
      include_other: form.include_other,
      confidence_threshold: form.choice_confidence_threshold,
    }
  }
  if (form.enable_score) {
    questions.score = {
      criteria: form.score_levels.map((level) => level.trim()).filter(Boolean),
      confidence_threshold: form.score_confidence_threshold,
    }
  }

  return {
    name: form.name.trim(),
    description: form.question.trim(),
    metric_type: form.enable_choice ? 'text' : 'number',
    trigger: 'always',
    enabled: true,
    metric_origin: 'custom',
    supported_surfaces: ['agent'],
    enabled_surfaces: ['agent'],
    custom_data_type: 'jev',
    custom_config: {
      state_source: form.state_source,
      questions,
    },
    tags: ['jev'],
    capture_rationale: false,
  }
}

export function jevFormIsValid(form: JevMetricFormValue): boolean {
  if (!form.name.trim() || !form.question.trim()) return false
  if (!form.enable_noul && !form.enable_choice && !form.enable_score) return false
  if (form.enable_choice && form.choices.filter((row) => row.key.trim()).length < 1) {
    return false
  }
  if (form.enable_score && form.score_levels.filter((level) => level.trim()).length < 2) {
    return false
  }
  return true
}

function buildPreview(form: JevMetricFormValue) {
  const payload = jevFormToPayload(form)
  const questionId = (payload.name || 'question').toLowerCase().replace(/\s+/g, '_') || 'question'
  const questionsCfg = (payload.custom_config.questions || {}) as Record<string, any>
  const requestQuestions: Record<string, unknown> = {}
  const answers: Record<string, unknown> = {}
  if (questionsCfg.noul) {
    requestQuestions[`${questionId}:noul`] = {
      type: 'noul',
      instructions: payload.description || 'Your question',
      criteria: questionsCfg.noul.criteria,
    }
    answers[`${questionId}:noul`] = { type: 'noul', noul: 0.95 }
  }
  if (questionsCfg.choice) {
    const keys = Object.keys(questionsCfg.choice.criteria || {})
    const first = keys[0] || 'option'
    const second = keys[1] || 'other'
    requestQuestions[`${questionId}:choice`] = {
      type: 'choice',
      instructions: payload.description || 'Your question',
      criteria: questionsCfg.choice.criteria,
    }
    answers[`${questionId}:choice`] = {
      type: 'choice',
      choice: first,
      probabilities: { [first]: 0.88, [second]: 0.12 },
      confidence: 0.81,
    }
  }
  if (questionsCfg.score) {
    requestQuestions[`${questionId}:score`] = {
      type: 'score',
      instructions: payload.description || 'Your question',
      criteria: questionsCfg.score.criteria,
    }
    answers[`${questionId}:score`] = {
      type: 'score',
      score: 1.05,
      legend: { '0': 'Calm', '1': 'Frustrated', '2': 'Very angry' },
      probabilities: { '0': 0.0, '1': 0.95, '2': 0.05 },
      confidence: 0.92,
    }
  }
  return {
    request: {
      state:
        form.state_source === 'user'
          ? [{ speaker: 'user', text: 'Help! My payouts have been failing for 3 days.' }]
          : form.state_source === 'agent'
            ? [{ speaker: 'agent', text: 'I can look that up for you right now.' }]
            : [
                { speaker: 'user', text: 'Help! My payouts have been failing for 3 days.' },
                { speaker: 'agent', text: 'I can look that up for you right now.' },
              ],
      model: 'jev-latest',
      questions: requestQuestions,
    },
    response: {
      model: 'jev-1.13.0',
      answers,
      usage: { input_tokens: 318, output_tokens: 34 },
    },
  }
}

interface JevMetricFormProps {
  value: JevMetricFormValue
  onChange: (next: JevMetricFormValue) => void
}

export default function JevMetricForm({ value, onChange }: JevMetricFormProps) {
  const preview = buildPreview(value)
  const canAddChoice = value.choices.length < 255
  const canAddScore = value.score_levels.length < 10

  const [advancedOpen, setAdvancedOpen] = useState(value.state_source !== 'both')

  const toggle = (key: 'enable_noul' | 'enable_choice' | 'enable_score') => {
    onChange({ ...value, [key]: !value[key] })
  }

  return (
    <div className="space-y-5">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
        <input
          value={value.name}
          onChange={(e) => onChange({ ...value, name: e.target.value })}
          className={INPUT_CLASS}
          placeholder="Urgency"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Question</label>
        <textarea
          value={value.question}
          onChange={(e) => onChange({ ...value, question: e.target.value })}
          className={INPUT_CLASS}
          rows={3}
          placeholder="Does this convey urgency?"
        />
      </div>

      <div className="space-y-3">
        <div>
          <p className="text-sm font-medium text-gray-700">Answers</p>
          <p className="text-xs text-gray-500 mt-0.5">
            All three sit in one list. Noul starts on; include choice or score
            to drop down their fields. Each type is scored independently.
          </p>
        </div>

        <div className="max-h-[28rem] overflow-y-auto space-y-3 pr-0.5">
          <section className="rounded-lg border border-gray-200 p-3 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <span className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-800">
                Noul
                <DefinitionTip label="Noul">
                  Probability that the answer is yes, from 0 to 1. The table
                  shows Yes or No at a 0.5 threshold, with the probability in
                  brackets — for example Yes (0.95). Noul is never sent to
                  human review.
                </DefinitionTip>
              </span>
              <IncludeToggle
                checked={value.enable_noul}
                onChange={() => toggle('enable_noul')}
                label="Include noul"
              />
            </div>
            {value.enable_noul && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Yes means
                  </label>
                  <input
                    value={value.noul_true}
                    onChange={(e) => onChange({ ...value, noul_true: e.target.value })}
                    className={INPUT_CLASS}
                    placeholder="Explicitly time-sensitive"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    No means
                  </label>
                  <input
                    value={value.noul_false}
                    onChange={(e) => onChange({ ...value, noul_false: e.target.value })}
                    className={INPUT_CLASS}
                    placeholder="No urgency expressed"
                  />
                </div>
              </div>
            )}
          </section>

          <section className="rounded-lg border border-gray-200 p-3 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <span className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-800">
                Choice
                <DefinitionTip label="Choice">
                  Pick exactly one option. The model returns the option, per-option
                  probabilities, and a confidence. If confidence is missing or
                  below the threshold, the row is flagged Needs human review.
                </DefinitionTip>
              </span>
              <IncludeToggle
                checked={value.enable_choice}
                onChange={() => toggle('enable_choice')}
                label="Include choice"
              />
            </div>
            {value.enable_choice && (
              <div className="space-y-3">
                {value.choices.map((row, idx) => (
                  <div key={idx} className="grid grid-cols-12 gap-2 items-start">
                    <input
                      value={row.key}
                      onChange={(e) => {
                        const choices = value.choices.slice()
                        choices[idx] = { ...row, key: e.target.value }
                        onChange({ ...value, choices })
                      }}
                      className={`${INPUT_CLASS} col-span-4`}
                      placeholder="billing"
                    />
                    <input
                      value={row.description}
                      onChange={(e) => {
                        const choices = value.choices.slice()
                        choices[idx] = { ...row, description: e.target.value }
                        onChange({ ...value, choices })
                      }}
                      className={`${INPUT_CLASS} col-span-7`}
                      placeholder="Payments, invoicing, refunds"
                    />
                    <button
                      type="button"
                      disabled={value.choices.length <= 1}
                      onClick={() =>
                        onChange({
                          ...value,
                          choices: value.choices.filter((_, i) => i !== idx),
                        })
                      }
                      className="col-span-1 mt-2 text-gray-400 hover:text-red-600 disabled:opacity-30"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  disabled={!canAddChoice}
                  onClick={() =>
                    onChange({
                      ...value,
                      choices: [...value.choices, { key: '', description: '' }],
                    })
                  }
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 hover:text-primary-700 disabled:opacity-40"
                >
                  <Plus className="w-4 h-4" />
                  Add choice
                </button>
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={value.include_other}
                    onChange={(e) =>
                      onChange({ ...value, include_other: e.target.checked })
                    }
                  />
                  Include &quot;Something else&quot; (other)
                </label>
                <ConfidenceSlider
                  value={value.choice_confidence_threshold}
                  onChange={(choice_confidence_threshold) =>
                    onChange({ ...value, choice_confidence_threshold })
                  }
                />
              </div>
            )}
          </section>

          <section className="rounded-lg border border-gray-200 p-3 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <span className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-800">
                Score
                <DefinitionTip label="Score">
                  Ordered levels, such as Calm, Frustrated, Very angry. The
                  table shows the winner level (highest probability, otherwise
                  the nearest legend index). Full score, probabilities, and
                  legend appear after you click the cell. Low or missing
                  confidence flags Needs human review.
                </DefinitionTip>
              </span>
              <IncludeToggle
                checked={value.enable_score}
                onChange={() => toggle('enable_score')}
                label="Include score"
              />
            </div>
            {value.enable_score && (
              <div className="space-y-3">
                {value.score_levels.map((level, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <span className="w-8 text-xs font-semibold text-gray-500">{idx}</span>
                    <input
                      value={level}
                      onChange={(e) => {
                        const score_levels = value.score_levels.slice()
                        score_levels[idx] = e.target.value
                        onChange({ ...value, score_levels })
                      }}
                      className={INPUT_CLASS}
                      placeholder={
                        idx === 0 ? 'Calm' : idx === 1 ? 'Frustrated' : 'Very angry'
                      }
                    />
                    <button
                      type="button"
                      disabled={value.score_levels.length <= 2}
                      onClick={() =>
                        onChange({
                          ...value,
                          score_levels: value.score_levels.filter((_, i) => i !== idx),
                        })
                      }
                      className="text-gray-400 hover:text-red-600 disabled:opacity-30"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  disabled={!canAddScore}
                  onClick={() =>
                    onChange({ ...value, score_levels: [...value.score_levels, ''] })
                  }
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 hover:text-primary-700 disabled:opacity-40"
                >
                  <Plus className="w-4 h-4" />
                  Add level
                </button>
                <ConfidenceSlider
                  value={value.score_confidence_threshold}
                  onChange={(score_confidence_threshold) =>
                    onChange({ ...value, score_confidence_threshold })
                  }
                />
              </div>
            )}
          </section>
        </div>
      </div>

      <details
        className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs"
        open={advancedOpen}
        onToggle={(e) => setAdvancedOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary className="cursor-pointer font-medium text-gray-700 list-none flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5">
            Advanced
            <DefinitionTip label="State">
              Defaults to both user and agent turns. Open this to score only
              one speaker. Narrator and other lines are always dropped.
            </DefinitionTip>
          </span>
          <span className="text-[11px] font-normal text-gray-500">
            State: {value.state_source === 'user'
              ? 'User turns'
              : value.state_source === 'agent'
                ? 'Agent turns'
                : 'Both'}
          </span>
        </summary>
        <div className="mt-3">
          <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1">
            State
          </label>
          <p className="text-xs text-gray-500 mb-2">
            Which speaker turns become the classification state. Default is both.
          </p>
          <div className="inline-flex rounded-md border border-gray-200 bg-white p-1 text-xs font-medium">
            {(
              [
                { id: 'user', label: 'User turns' },
                { id: 'agent', label: 'Agent turns' },
                { id: 'both', label: 'Both' },
              ] as Array<{ id: JevStateSource; label: string }>
            ).map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => onChange({ ...value, state_source: opt.id })}
                className={`px-3 py-1.5 rounded ${
                  value.state_source === opt.id
                    ? 'bg-gray-900 text-white shadow-sm'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </details>

      <details className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs">
        <summary className="cursor-pointer font-medium text-gray-700 list-none flex items-center justify-between gap-2">
          <span>Example request / response</span>
          <span className="text-[11px] font-normal text-gray-500">Show JSON</span>
        </summary>
        <p className="mt-2 text-[11px] text-gray-500">
          Reference payload for one classification request on the filtered transcript
          state. Enabled types are isolated questions on that same state.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-3">
          <JsonExample
            tone="input"
            label="Request"
            badge="Input"
            value={preview.request}
          />
          <JsonExample
            tone="output"
            label="Response"
            badge="Output"
            value={preview.response}
          />
        </div>
      </details>
    </div>
  )
}

function DefinitionTip({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <span className="relative inline-flex items-center group">
      <button
        type="button"
        aria-label={`${label} definition`}
        className="text-gray-400 hover:text-gray-600 focus:outline-none"
      >
        <Info className="w-3.5 h-3.5" />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute left-0 top-full z-30 mt-1 hidden w-72 rounded-md border border-gray-200 bg-white p-3 text-left text-xs font-normal leading-relaxed text-gray-700 shadow-lg group-hover:block group-focus-within:block"
      >
        {children}
      </span>
    </span>
  )
}

function JsonExample({
  tone,
  label,
  badge,
  value,
}: {
  tone: 'input' | 'output'
  label: string
  badge: string
  value: unknown
}) {
  const isInput = tone === 'input'
  return (
    <div
      className={`rounded-md border overflow-hidden ${
        isInput ? 'border-sky-200' : 'border-emerald-200'
      }`}
    >
      <div
        className={`flex items-center justify-between px-2.5 py-1.5 ${
          isInput ? 'bg-sky-50' : 'bg-emerald-50'
        }`}
      >
        <span
          className={`text-[11px] font-semibold uppercase tracking-wide ${
            isInput ? 'text-sky-800' : 'text-emerald-800'
          }`}
        >
          {label}
        </span>
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
            isInput
              ? 'bg-sky-100 text-sky-700'
              : 'bg-emerald-100 text-emerald-700'
          }`}
        >
          {badge}
        </span>
      </div>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words bg-slate-950 p-2.5 font-mono text-[11px] leading-relaxed">
        {colorizeJson(JSON.stringify(value, null, 2))}
      </pre>
    </div>
  )
}

function IncludeToggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: () => void
  label: string
}) {
  return (
    <label className="inline-flex items-center gap-2 text-xs font-medium text-gray-600 cursor-pointer select-none">
      <span>{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={(e) => {
          e.preventDefault()
          onChange()
        }}
        className={`relative inline-flex h-5 w-9 items-center rounded-full transition ${
          checked ? 'bg-primary-600' : 'bg-gray-200'
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition ${
            checked ? 'translate-x-4' : 'translate-x-0.5'
          }`}
        />
      </button>
    </label>
  )
}

function ConfidenceSlider({
  value,
  onChange,
}: {
  value: number
  onChange: (next: number) => void
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        Confidence threshold ({value.toFixed(2)})
      </label>
      <p className="text-xs text-gray-500 mb-2">
        Answers below this confidence are flagged for human review.
      </p>
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
    </div>
  )
}
