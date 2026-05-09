import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Sparkles, AlertCircle, ExternalLink } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'

export default function OptimizeJudge({ datasetId }: { datasetId: string }) {
  const [evaluatorId, setEvaluatorId] = useState<string>('')
  const [devRatio, setDevRatio] = useState<number>(0.5)
  const [maxCalls, setMaxCalls] = useState<number>(20)
  const [error, setError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<{
    runId: string
    devCount: number
    testCount: number
  } | null>(null)

  const { data: evaluators = [] } = useQuery({
    queryKey: ['evaluators'],
    queryFn: () => apiClient.listEvaluators(),
  })

  const { data: models = [] } = useQuery({
    queryKey: ['judge-alignment', 'available-models'],
    queryFn: () => apiClient.listJudgeCapableModels(),
  })

  const judgeReady = evaluators.filter(
    (e: any) => e.custom_prompt && e.llm_provider && e.llm_model
  )

  const optimizeMutation = useMutation({
    mutationFn: () =>
      apiClient.optimizeJudge(datasetId, {
        evaluator_id: evaluatorId,
        dev_ratio: devRatio,
        max_metric_calls: maxCalls,
      }),
    onSuccess: (res) => {
      setError(null)
      setLastResult({
        runId: res.optimization_run_id,
        devCount: res.dev_sample_count,
        testCount: res.test_sample_count,
      })
    },
    onError: (e: any) => {
      setError(e?.response?.data?.detail || e?.message || 'Failed to start optimization')
    },
  })

  return (
    <div className="space-y-6">
      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-yellow-600" /> Optimize judge prompt
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          Splits your labeled samples into a balanced dev / test set, runs GEPA
          to refine the judge's <code>custom_prompt</code> against dev F1, then
          reports test-set F1 to detect overfitting. The best candidate is
          available on the existing Prompt Optimization page.
        </p>

        {models.length === 0 && (
          <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded text-sm text-amber-800 flex items-start gap-2">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <div>
              No LLM-capable AI providers configured.{' '}
              <Link
                to="/integrations"
                className="font-medium underline hover:text-amber-900"
              >
                Add one in Integrations
              </Link>{' '}
              to populate the model dropdown on your evaluators.
            </div>
          </div>
        )}

        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-medium text-gray-900">
              Evaluator (judge to optimize)
            </label>
            <select
              value={evaluatorId}
              onChange={(e) => setEvaluatorId(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-400"
            >
              <option value="">Select an evaluator</option>
              {judgeReady.map((e: any) => (
                <option key={e.id} value={e.id}>
                  {e.name || e.evaluator_id} - {e.llm_provider}/{e.llm_model}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-sm font-medium text-gray-900">
              Dev split ratio: {(devRatio * 100).toFixed(0)}%
            </label>
            <input
              type="range"
              min={0.1}
              max={0.9}
              step={0.05}
              value={devRatio}
              onChange={(e) => setDevRatio(parseFloat(e.target.value))}
              className="mt-2 w-full"
            />
            <p className="mt-1 text-xs text-gray-500">
              Higher = more samples to fit on, fewer to validate against.
            </p>
          </div>
          <div>
            <label className="text-sm font-medium text-gray-900">
              Max optimization trials
            </label>
            <input
              type="number"
              min={1}
              max={200}
              value={maxCalls}
              onChange={(e) =>
                setMaxCalls(Math.max(1, Math.min(200, parseInt(e.target.value, 10) || 20)))
              }
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-400"
            />
          </div>
          <div className="flex items-end">
            <Button
              variant="primary"
              leftIcon={<Sparkles className="h-4 w-4" />}
              onClick={() => optimizeMutation.mutate()}
              isLoading={optimizeMutation.isPending}
              disabled={!evaluatorId}
            >
              Start GEPA
            </Button>
          </div>
        </div>

        {error && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
            {error}
          </div>
        )}

        {lastResult && (
          <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded">
            <p className="text-sm text-green-800">
              Optimization run started. Dev samples: {lastResult.devCount},
              Test samples: {lastResult.testCount}.
            </p>
            <Link
              to="/prompt-optimization"
              className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-green-800 hover:text-green-900 underline"
            >
              View progress in Prompt Optimization{' '}
              <ExternalLink className="h-3.5 w-3.5" />
            </Link>
          </div>
        )}
      </div>
    </div>
  )
}
