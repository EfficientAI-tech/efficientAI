import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { X, Save, RotateCcw } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'

export default function SettingsPanel({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['judge-alignment', 'settings'],
    queryFn: () => apiClient.getJudgeAlignmentSettings(),
  })

  const [evalMin, setEvalMin] = useState<number>(20)
  const [optMin, setOptMin] = useState<number>(50)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (data) {
      setEvalMin(data.min_labels_to_evaluate)
      setOptMin(data.min_labels_to_optimize)
    }
  }, [data])

  const mutation = useMutation({
    mutationFn: () =>
      apiClient.updateJudgeAlignmentSettings({
        min_labels_to_evaluate: evalMin,
        min_labels_to_optimize: optMin,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['judge-alignment', 'settings'] })
      onClose()
    },
    onError: (e: any) => {
      setError(e?.response?.data?.detail || e?.message || 'Failed to save')
    },
  })

  const restoreDefaults = () => {
    if (data?.defaults) {
      setEvalMin(data.defaults.min_labels_to_evaluate)
      setOptMin(data.defaults.min_labels_to_optimize)
    }
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black bg-opacity-40 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">
            Judge Alignment Settings
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-5">
          <p className="text-sm text-gray-600">
            Tune the minimum number of human-labeled samples required to unlock
            evaluation and optimization. Defaults follow AlignEval's
            recommendations.
          </p>

          {isLoading ? (
            <div className="flex items-center justify-center h-24">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-900" />
            </div>
          ) : (
            <>
              <Field
                label="Min labels to evaluate"
                hint="Samples needed before the Evaluate Judge action unlocks."
                value={evalMin}
                onChange={setEvalMin}
                defaultValue={data?.defaults.min_labels_to_evaluate}
              />
              <Field
                label="Min labels to optimize"
                hint="Samples needed before GEPA optimisation can run. Must be ≥ the evaluate threshold."
                value={optMin}
                onChange={setOptMin}
                defaultValue={data?.defaults.min_labels_to_optimize}
              />
            </>
          )}

          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200 bg-gray-50 rounded-b-lg">
          <Button
            variant="ghost"
            leftIcon={<RotateCcw className="h-4 w-4" />}
            onClick={restoreDefaults}
            disabled={!data}
          >
            Restore defaults
          </Button>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              leftIcon={<Save className="h-4 w-4" />}
              onClick={() => mutation.mutate()}
              isLoading={mutation.isPending}
              disabled={isLoading}
            >
              Save
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  hint,
  value,
  onChange,
  defaultValue,
}: {
  label: string
  hint: string
  value: number
  onChange: (v: number) => void
  defaultValue?: number
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-gray-900">{label}</label>
        {defaultValue !== undefined && (
          <span className="text-xs text-gray-400">default: {defaultValue}</span>
        )}
      </div>
      <input
        type="number"
        min={1}
        value={value}
        onChange={(e) => onChange(Math.max(1, parseInt(e.target.value, 10) || 1))}
        className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-400 focus:border-transparent"
      />
      <p className="mt-1 text-xs text-gray-500">{hint}</p>
    </div>
  )
}
