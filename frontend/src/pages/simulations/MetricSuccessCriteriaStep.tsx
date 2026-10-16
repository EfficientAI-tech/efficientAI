import type { MetricSuccessCriterion } from '../../types/api'
import {
  classificationChoiceOptions,
  classificationScoreLevels,
  defaultCriterionForMetric,
  inferCriterionKind,
  numberRange,
} from './metricSuccessCriteriaUtils'
import {
  flattenMetrics,
  getEnabledChildren,
  type MetricRow,
} from '../evaluators/components/metricSelectionUtils'

interface Props {
  metrics: MetricRow[]
  selectedMetricIds: string[]
  criteria: MetricSuccessCriterion[]
  onChange: (next: MetricSuccessCriterion[]) => void
}

function patchCriterion(
  criteria: MetricSuccessCriterion[],
  metricId: string,
  patch: Partial<MetricSuccessCriterion>,
): MetricSuccessCriterion[] {
  return criteria.map((c) => (c.metric_id === metricId ? { ...c, ...patch } : c))
}

function toggleInList(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

function CriterionCard({
  metric,
  criterion,
  onChange,
}: {
  metric: MetricRow
  criterion: MetricSuccessCriterion
  onChange: (next: MetricSuccessCriterion) => void
}) {
  const kind = criterion.kind

  if (kind === 'text') {
    return (
      <p className="text-sm text-gray-600">
        Free-text metric — shown on each trial transcript but does not affect pass/fail.
      </p>
    )
  }

  if (kind === 'boolean') {
    return (
      <div className="flex flex-wrap gap-4 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="radio"
            checked={criterion.success_when !== 'no'}
            onChange={() => onChange({ ...criterion, success_when: 'yes' })}
          />
          Pass when Yes
        </label>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            checked={criterion.success_when === 'no'}
            onChange={() => onChange({ ...criterion, success_when: 'no' })}
          />
          Pass when No
        </label>
      </div>
    )
  }

  if (kind === 'rating') {
    return (
      <div className="space-y-2 text-sm">
        <label className="block">
          Pass when rating {criterion.op === 'lte' ? '≤' : '≥'}{' '}
          {(criterion.threshold ?? 0.7).toFixed(2)}
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={criterion.threshold ?? 0.7}
            onChange={(e) =>
              onChange({ ...criterion, op: 'gte', threshold: Number(e.target.value) })
            }
            className="mt-1 w-full"
          />
        </label>
      </div>
    )
  }

  if (kind === 'number') {
    const range = numberRange(metric)
    return (
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label>
          Operator
          <select
            value={criterion.op || 'gte'}
            onChange={(e) =>
              onChange({
                ...criterion,
                op: e.target.value as MetricSuccessCriterion['op'],
              })
            }
            className="mt-1 block rounded-lg border border-gray-300 px-2 py-1.5"
          >
            <option value="gte">≥</option>
            <option value="gt">&gt;</option>
            <option value="lte">≤</option>
            <option value="lt">&lt;</option>
          </select>
        </label>
        <label>
          Threshold
          {range ? (
            <input
              type="range"
              min={range.min}
              max={range.max}
              step={(range.max - range.min) / 100 || 0.01}
              value={criterion.threshold ?? range.min}
              onChange={(e) => onChange({ ...criterion, threshold: Number(e.target.value) })}
              className="mt-1 block w-48"
            />
          ) : (
            <input
              type="number"
              value={criterion.threshold ?? ''}
              onChange={(e) => onChange({ ...criterion, threshold: Number(e.target.value) })}
              className="mt-1 block w-32 rounded-lg border border-gray-300 px-2 py-1.5"
            />
          )}
        </label>
      </div>
    )
  }

  if (kind === 'enum' || kind === 'category_single') {
    const options =
      kind === 'enum'
        ? ((metric.custom_config as { options?: string[] })?.options ?? [])
        : getEnabledChildren(metric).map((c) => c.name)
    return (
      <div className="space-y-1">
        <p className="text-xs text-gray-500">Select one or more values that count as success.</p>
        <div className="flex flex-wrap gap-2">
          {options.map((opt) => (
            <label
              key={opt}
              className="flex items-center gap-1.5 rounded-md border border-gray-200 px-2 py-1 text-sm"
            >
              <input
                type="checkbox"
                checked={(criterion.success_values || []).includes(opt)}
                onChange={() =>
                  onChange({
                    ...criterion,
                    success_values: toggleInList(criterion.success_values || [], opt),
                  })
                }
              />
              {opt}
            </label>
          ))}
        </div>
      </div>
    )
  }

  if (kind === 'category_multi') {
    const children = getEnabledChildren(metric)
    const rules = criterion.label_rules || []
    const ruleFor = (childId: string) => rules.find((r) => r.child_id === childId)?.expect

    return (
      <div className="space-y-2 text-sm">
        <p className="text-xs text-gray-500">
          Set each label to must be Yes, must be No, or leave as Ignore.
        </p>
        {children.map((child) => {
          const expect = ruleFor(child.id)
          return (
            <div key={child.id} className="flex flex-wrap items-center gap-2">
              <span className="min-w-[8rem] font-medium text-gray-800">{child.name}</span>
              <select
                value={expect ?? 'ignore'}
                onChange={(e) => {
                  const val = e.target.value
                  let next = rules.filter((r) => r.child_id !== child.id)
                  if (val === 'yes' || val === 'no') {
                    next = [...next, { child_id: child.id, expect: val }]
                  }
                  onChange({ ...criterion, label_rules: next })
                }}
                className="rounded-lg border border-gray-300 px-2 py-1"
              >
                <option value="ignore">Ignore</option>
                <option value="yes">Must be Yes</option>
                <option value="no">Must be No</option>
              </select>
            </div>
          )
        })}
      </div>
    )
  }

  if (kind === 'classification') {
    const cfg = metric.custom_config as Record<
      string,
      { enabled?: boolean; criteria?: Record<string, string> | string[] }
    >
    const q = criterion.questions || {}
    return (
      <div className="space-y-4 text-sm">
        {cfg?.noul?.enabled ? (
          <div>
            <div className="font-medium text-gray-800">Yes / No question</div>
            <label className="mt-1 flex items-center gap-2">
              <input
                type="checkbox"
                checked={Boolean(q.noul)}
                onChange={(e) => {
                  const questions = { ...q }
                  if (e.target.checked) questions.noul = { success_when: 'yes' }
                  else delete questions.noul
                  onChange({ ...criterion, questions })
                }}
              />
              Use for pass/fail
            </label>
            {q.noul ? (
              <div className="mt-2 flex gap-4">
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={q.noul.success_when !== 'no'}
                    onChange={() =>
                      onChange({
                        ...criterion,
                        questions: { ...q, noul: { success_when: 'yes' } },
                      })
                    }
                  />
                  Pass when Yes
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={q.noul.success_when === 'no'}
                    onChange={() =>
                      onChange({
                        ...criterion,
                        questions: { ...q, noul: { success_when: 'no' } },
                      })
                    }
                  />
                  Pass when No
                </label>
              </div>
            ) : null}
          </div>
        ) : null}
        {cfg?.choice?.enabled ? (
          <div>
            <div className="font-medium text-gray-800">Choice question</div>
            <label className="mt-1 flex items-center gap-2">
              <input
                type="checkbox"
                checked={Boolean(q.choice)}
                onChange={(e) => {
                  const questions = { ...q }
                  if (e.target.checked) questions.choice = { success_values: [] }
                  else delete questions.choice
                  onChange({ ...criterion, questions })
                }}
              />
              Use for pass/fail
            </label>
            {q.choice ? (
              <div className="mt-2 flex flex-wrap gap-2">
                {classificationChoiceOptions(metric).map((opt) => (
                  <label
                    key={opt}
                    className="flex items-center gap-1.5 rounded-md border border-gray-200 px-2 py-1"
                  >
                    <input
                      type="checkbox"
                      checked={q.choice!.success_values.includes(opt)}
                      onChange={() =>
                        onChange({
                          ...criterion,
                          questions: {
                            ...q,
                            choice: {
                              success_values: toggleInList(q.choice!.success_values, opt),
                            },
                          },
                        })
                      }
                    />
                    {opt}
                  </label>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        {cfg?.score?.enabled ? (
          <div>
            <div className="font-medium text-gray-800">Score level question</div>
            <label className="mt-1 flex items-center gap-2">
              <input
                type="checkbox"
                checked={Boolean(q.score)}
                onChange={(e) => {
                  const questions = { ...q }
                  if (e.target.checked) questions.score = { success_values: [] }
                  else delete questions.score
                  onChange({ ...criterion, questions })
                }}
              />
              Use for pass/fail
            </label>
            {q.score ? (
              <div className="mt-2 flex flex-wrap gap-2">
                {classificationScoreLevels(metric).map((level) => (
                  <label
                    key={level}
                    className="flex items-center gap-1.5 rounded-md border border-gray-200 px-2 py-1"
                  >
                    <input
                      type="checkbox"
                      checked={q.score!.success_values.includes(level)}
                      onChange={() =>
                        onChange({
                          ...criterion,
                          questions: {
                            ...q,
                            score: {
                              success_values: toggleInList(q.score!.success_values, level),
                            },
                          },
                        })
                      }
                    />
                    {level}
                  </label>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    )
  }

  return null
}

export default function MetricSuccessCriteriaStep({
  metrics,
  selectedMetricIds,
  criteria,
  onChange,
}: Props) {
  const flat = flattenMetrics(metrics)
  const byId = new Map(flat.map((m) => [m.id, m]))

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        A trial passes only when every metric below meets its rule. Set polarity for yes/no metrics
        and pick success values for labels and classifications.
      </p>
      {selectedMetricIds.map((id) => {
        const metric = byId.get(id)
        const criterion =
          criteria.find((c) => c.metric_id === id) ??
          (metric ? defaultCriterionForMetric(metric) : null)
        if (!metric || !criterion) return null
        const kindLabel = inferCriterionKind(metric)
        return (
          <div key={id} className="rounded-lg border border-gray-200 p-4">
            <div className="mb-3">
              <h4 className="text-sm font-semibold text-gray-900">{metric.name}</h4>
              <p className="text-xs capitalize text-gray-500">{kindLabel.replace(/_/g, ' ')}</p>
            </div>
            <CriterionCard
              metric={metric}
              criterion={criterion}
              onChange={(next) => onChange(patchCriterion(criteria, id, next))}
            />
          </div>
        )
      })}
    </div>
  )
}
