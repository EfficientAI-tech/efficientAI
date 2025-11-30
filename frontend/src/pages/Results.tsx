import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { Clock, CheckCircle, XCircle, Loader } from 'lucide-react'

interface EvaluatorResult {
  id: string
  result_id: string
  name: string
  timestamp: string
  duration_seconds: number | null
  status: 'in_progress' | 'completed' | 'failed'
  metric_scores: Record<string, { value: any; type: string; metric_name: string }> | null
  error_message: string | null
}

interface Metric {
  id: string
  name: string
  metric_type: 'number' | 'boolean' | 'rating'
  enabled: boolean
}

export default function Results() {
  const { data: results = [], isLoading: loadingResults } = useQuery({
    queryKey: ['evaluator-results'],
    queryFn: () => apiClient.listEvaluatorResults(),
  })

  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics'],
    queryFn: () => apiClient.listMetrics(),
  })

  // Get enabled metrics for column headers
  const enabledMetrics = metrics.filter((m: Metric) => m.enabled)

  const formatDuration = (seconds: number | null): string => {
    if (!seconds) return 'N/A'
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const formatTimestamp = (timestamp: string): string => {
    return new Date(timestamp).toLocaleString()
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-green-500" />
      case 'failed':
        return <XCircle className="w-4 h-4 text-red-500" />
      case 'in_progress':
        return <Loader className="w-4 h-4 text-blue-500 animate-spin" />
      default:
        return null
    }
  }

  const getStatusBadge = (status: string) => {
    const baseClasses = "px-2 py-1 text-xs font-medium rounded"
    switch (status) {
      case 'completed':
        return `${baseClasses} bg-green-100 text-green-800`
      case 'failed':
        return `${baseClasses} bg-red-100 text-red-800`
      case 'in_progress':
        return `${baseClasses} bg-blue-100 text-blue-800`
      default:
        return `${baseClasses} bg-gray-100 text-gray-800`
    }
  }

  const formatMetricValue = (value: any, type: string): string => {
    if (value === null || value === undefined) return 'N/A'
    if (type === 'boolean') return value ? 'Yes' : 'No'
    if (type === 'rating') return value?.toString() || 'N/A'
    if (type === 'number') return value?.toString() || 'N/A'
    return String(value)
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Results</h1>
        <p className="mt-2 text-sm text-gray-600">
          View evaluation results from running evaluators
        </p>
      </div>

      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          {loadingResults ? (
            <div className="p-6 text-center text-gray-500">Loading...</div>
          ) : results.length === 0 ? (
            <div className="p-12 text-center">
              <p className="text-gray-500 mb-4">No results yet. Run an evaluator to see results here.</p>
            </div>
          ) : (
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    ID
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Name
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Timestamp
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Duration
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  {enabledMetrics.map((metric: Metric) => (
                    <th
                      key={metric.id}
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                    >
                      {metric.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {results.map((result: EvaluatorResult) => (
                  <tr key={result.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="font-mono font-semibold text-sm text-gray-900">
                        {result.result_id}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm font-medium text-gray-900">{result.name}</div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm text-gray-500">{formatTimestamp(result.timestamp)}</div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center text-sm text-gray-500">
                        <Clock className="w-4 h-4 mr-1" />
                        {formatDuration(result.duration_seconds)}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center space-x-2">
                        {getStatusIcon(result.status)}
                        <span className={getStatusBadge(result.status)}>
                          {result.status.toUpperCase().replace('_', ' ')}
                        </span>
                      </div>
                    </td>
                    {enabledMetrics.map((metric: Metric) => {
                      const score = result.metric_scores?.[metric.id]
                      return (
                        <td key={metric.id} className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm text-gray-900">
                            {score ? formatMetricValue(score.value, score.type) : 'N/A'}
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

