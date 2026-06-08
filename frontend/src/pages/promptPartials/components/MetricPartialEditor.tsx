import { Plus, Trash2 } from 'lucide-react'
import type { MetricPartialContent, MetricPartialChild } from '../metricPartialUtils'

const inputClass =
  'w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent'

function defaultChildren(): MetricPartialChild[] {
  return [{ name: '', description: '', example: '' }]
}

export default function MetricPartialEditor({
  value,
  onChange,
  readOnly = false,
}: {
  value: MetricPartialContent
  onChange?: (next: MetricPartialContent) => void
  readOnly?: boolean
}) {
  const update = (patch: Partial<MetricPartialContent>) => {
    if (!onChange) return
    onChange({ ...value, ...patch })
  }

  const childRows =
    value.metric_kind === 'category'
      ? value.children && value.children.length > 0
        ? value.children
        : defaultChildren()
      : []

  const updateChild = (index: number, patch: Partial<MetricPartialChild>) => {
    if (!onChange || value.metric_kind !== 'category') return
    const nextChildren = childRows.map((child, childIndex) =>
      childIndex === index ? { ...child, ...patch } : child,
    )
    onChange({
      ...value,
      children: nextChildren,
    })
  }

  const addChild = () => {
    if (!onChange || value.metric_kind !== 'category') return
    onChange({
      ...value,
      children: [...childRows, { name: '', description: '', example: '' }],
    })
  }

  const removeChild = (index: number) => {
    if (!onChange || value.metric_kind !== 'category') return
    const remaining = childRows.filter((_child, childIndex) => childIndex !== index)
    onChange({
      ...value,
      children: remaining.length > 0 ? remaining : defaultChildren(),
    })
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Description {value.metric_kind === 'category' ? '(Prompt)' : ''}
        </label>
        {readOnly ? (
          <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-800 whitespace-pre-wrap">
            {value.description || '(empty)'}
          </div>
        ) : (
          <textarea
            value={value.description}
            onChange={(e) => update({ description: e.target.value })}
            rows={4}
            className={inputClass}
            placeholder={
              value.metric_kind === 'category'
                ? 'Tell the LLM what this metric measures. The labels below are the possible outcomes.'
                : 'Tell the LLM what to look for when evaluating this metric.'
            }
          />
        )}
      </div>

      {value.metric_kind === 'category' ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium text-gray-900">Label definitions</h4>
            {!readOnly ? (
              <button
                type="button"
                onClick={addChild}
                className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700"
              >
                <Plus className="h-3.5 w-3.5" />
                Add label
              </button>
            ) : null}
          </div>
          <div className="space-y-3">
            {childRows.map((child, index) => (
              <div
                key={index}
                className="rounded-xl border border-gray-200 bg-gray-50/70 p-3 space-y-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-gray-500">
                    Label {index + 1}
                  </span>
                  {!readOnly && childRows.length > 1 ? (
                    <button
                      type="button"
                      onClick={() => removeChild(index)}
                      className="inline-flex items-center gap-1 text-xs text-red-600 hover:text-red-700"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Remove
                    </button>
                  ) : null}
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Label name
                  </label>
                  {readOnly ? (
                    <div className="text-sm text-gray-900">{child.name || '(unnamed)'}</div>
                  ) : (
                    <input
                      value={child.name}
                      onChange={(e) => updateChild(index, { name: e.target.value })}
                      className={inputClass}
                      placeholder="e.g. Booked"
                    />
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Definition
                  </label>
                  {readOnly ? (
                    <div className="text-sm text-gray-800 whitespace-pre-wrap">
                      {child.description || '(empty)'}
                    </div>
                  ) : (
                    <textarea
                      value={child.description}
                      onChange={(e) =>
                        updateChild(index, { description: e.target.value })
                      }
                      rows={2}
                      className={inputClass}
                      placeholder="When should this label be chosen?"
                    />
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Example <span className="text-gray-400">(optional)</span>
                  </label>
                  {readOnly ? (
                    <div className="text-sm text-gray-800 whitespace-pre-wrap">
                      {child.example || '(none)'}
                    </div>
                  ) : (
                    <textarea
                      value={child.example}
                      onChange={(e) => updateChild(index, { example: e.target.value })}
                      rows={2}
                      className={inputClass}
                      placeholder="Example transcript snippet for this label"
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
