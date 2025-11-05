import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { BarChart3, TrendingUp, Clock, CheckCircle, AlertCircle } from 'lucide-react'

export default function Metrics() {
  const { data: evaluations, isLoading } = useQuery({
    queryKey: ['evaluations', 'list'],
    queryFn: () => apiClient.listEvaluations(0, 100),
  })

  if (isLoading) {
    return <div className="text-center py-12 text-gray-500">Loading metrics...</div>
  }

  // Calculate metrics from evaluations
  const totalEvaluations = evaluations?.length || 0
  const completedEvaluations = evaluations?.filter(e => e.status === 'completed').length || 0
  const pendingEvaluations = evaluations?.filter(e => e.status === 'pending').length || 0
  const failedEvaluations = evaluations?.filter(e => e.status === 'failed').length || 0
  
  const completionRate = totalEvaluations > 0 ? (completedEvaluations / totalEvaluations) * 100 : 0

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Metrics Dashboard</h1>
        <p className="mt-2 text-sm text-gray-600">
          View performance metrics and analytics for your evaluations
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <BarChart3 className="h-6 w-6 text-gray-400" />
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">Total Evaluations</dt>
                  <dd className="text-lg font-medium text-gray-900">{totalEvaluations}</dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <CheckCircle className="h-6 w-6 text-green-400" />
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">Completed</dt>
                  <dd className="text-lg font-medium text-gray-900">{completedEvaluations}</dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <Clock className="h-6 w-6 text-yellow-400" />
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">Pending</dt>
                  <dd className="text-lg font-medium text-gray-900">{pendingEvaluations}</dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <TrendingUp className="h-6 w-6 text-primary-400" />
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">Completion Rate</dt>
                  <dd className="text-lg font-medium text-gray-900">{completionRate.toFixed(1)}%</dd>
                </dl>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Detailed Metrics */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Evaluation Metrics</h2>
        </div>
        <div className="p-6">
          <p className="text-gray-500">
            Detailed metrics and analytics will be displayed here. This section can include:
          </p>
          <ul className="mt-4 list-disc list-inside text-gray-600 space-y-2">
            <li>Average WER (Word Error Rate) across all evaluations</li>
            <li>Average latency metrics</li>
            <li>Success rate trends over time</li>
            <li>Performance comparisons between different models</li>
            <li>Time-series charts and graphs</li>
          </ul>
        </div>
      </div>

      {/* Failed Evaluations Alert */}
      {failedEvaluations > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="flex">
            <AlertCircle className="h-5 w-5 text-yellow-400" />
            <div className="ml-3">
              <p className="text-sm text-yellow-800">
                <strong>Warning:</strong> {failedEvaluations} evaluation(s) have failed. 
                Review them in the Evaluations section.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

