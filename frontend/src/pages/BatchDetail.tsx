import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { ArrowLeft, Loader, Download, RefreshCw } from 'lucide-react'
import { format } from 'date-fns'

export default function BatchDetail() {
  const { id } = useParams<{ id: string }>()

  const { data: batch, isLoading: batchLoading } = useQuery({
    queryKey: ['batches', id],
    queryFn: () => apiClient.getBatch(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      // Poll if batch is pending or processing
      const data = query.state.data
      if (data?.status === 'pending' || data?.status === 'processing') {
        return 5000 // Poll every 5 seconds
      }
      return false
    },
  })

  const { data: results, isLoading: resultsLoading } = useQuery({
    queryKey: ['batches', id, 'results'],
    queryFn: () => apiClient.getBatchResults(id!),
    enabled: !!id && batch?.status === 'completed',
  })

  const handleExport = async (format: 'json' | 'csv') => {
    if (!id) return
    try {
      const blob = await apiClient.exportBatchResults(id, format)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `batch_${id}.${format}`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (error: any) {
      alert(`Export failed: ${error.response?.data?.detail || error.message}`)
    }
  }

  if (batchLoading) {
    return (
      <div className="text-center py-12">
        <Loader className="h-8 w-8 animate-spin text-primary-600 mx-auto" />
      </div>
    )
  }

  if (!batch) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Batch job not found</p>
        <Link to="/batch" className="mt-4 text-primary-600 hover:text-primary-700">
          ← Back to batch jobs
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <Link to="/batch" className="text-gray-400 hover:text-gray-600">
            <ArrowLeft className="h-6 w-6" />
          </Link>
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Batch Job Details</h1>
            <p className="mt-1 text-sm text-gray-600">ID: {batch.id}</p>
          </div>
        </div>
        <div className="flex items-center space-x-2">
          {batch.status === 'completed' && results && (
            <>
              <button
                onClick={() => handleExport('json')}
                className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
              >
                <Download className="h-4 w-4 mr-2" />
                Export JSON
              </button>
              <button
                onClick={() => handleExport('csv')}
                className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
              >
                <Download className="h-4 w-4 mr-2" />
                Export CSV
              </button>
            </>
          )}
          <span
            className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${
              batch.status === 'completed'
                ? 'bg-green-100 text-green-800'
                : batch.status === 'processing'
                ? 'bg-orange-100 text-orange-800'
                : 'bg-yellow-100 text-yellow-800'
            }`}
          >
            {batch.status.charAt(0).toUpperCase() + batch.status.slice(1)}
          </span>
        </div>
      </div>

      {/* Batch Info */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Batch Information</h2>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-sm font-medium text-gray-500">Total Files</dt>
            <dd className="mt-1 text-sm text-gray-900">{batch.total_files}</dd>
          </div>
          <div>
            <dt className="text-sm font-medium text-gray-500">Processed</dt>
            <dd className="mt-1 text-sm text-gray-900">{batch.processed_files}</dd>
          </div>
          <div>
            <dt className="text-sm font-medium text-gray-500">Failed</dt>
            <dd className="mt-1 text-sm text-gray-900">{batch.failed_files}</dd>
          </div>
          <div>
            <dt className="text-sm font-medium text-gray-500">Created</dt>
            <dd className="mt-1 text-sm text-gray-900">
              {format(new Date(batch.created_at), 'PPpp')}
            </dd>
          </div>
          {batch.completed_at && (
            <div>
              <dt className="text-sm font-medium text-gray-500">Completed</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {format(new Date(batch.completed_at), 'PPpp')}
              </dd>
            </div>
          )}
        </dl>

        {/* Progress */}
        <div className="mt-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Progress</span>
            <span className="text-sm text-gray-500">
              {batch.total_files > 0
                ? Math.round((batch.processed_files / batch.total_files) * 100)
                : 0}
              %
            </span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2.5">
            <div
              className="bg-primary-600 h-2.5 rounded-full transition-all duration-300"
              style={{
                width: `${batch.total_files > 0 ? (batch.processed_files / batch.total_files) * 100 : 0}%`,
              }}
            />
          </div>
        </div>
      </div>

      {/* Results */}
      {batch.status === 'completed' && results && (
        <>
          {resultsLoading ? (
            <div className="text-center py-8">
              <Loader className="h-6 w-6 animate-spin text-primary-600 mx-auto" />
            </div>
          ) : (
            <>
              {/* Aggregated Metrics */}
              {results.aggregated_metrics &&
                Object.keys(results.aggregated_metrics).length > 0 && (
                  <div className="bg-white shadow rounded-lg p-6">
                    <h2 className="text-lg font-medium text-gray-900 mb-4">
                      Aggregated Metrics
                    </h2>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                      {Object.entries(results.aggregated_metrics).map(([key, value]) => (
                        <div key={key} className="bg-gray-50 rounded-lg p-4">
                          <dt className="text-sm font-medium text-gray-500 uppercase">
                            {key.replace(/_/g, ' ')}
                          </dt>
                          <dd className="mt-1 text-2xl font-semibold text-gray-900">
                            {typeof value === 'number' ? value.toFixed(4) : String(value)}
                          </dd>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

              {/* Individual Results */}
              {results.individual_results.length > 0 && (
                <div className="bg-white shadow rounded-lg overflow-hidden">
                  <div className="px-4 py-5 sm:p-6 border-b border-gray-200">
                    <h2 className="text-lg font-medium text-gray-900">
                      Individual Results ({results.individual_results.length})
                    </h2>
                  </div>
                  <div className="divide-y divide-gray-200">
                    {results.individual_results.map((result, index) => (
                      <div key={index} className="px-4 py-4 sm:p-6">
                        <div className="flex items-center justify-between mb-3">
                          <Link
                            to={`/evaluations/${result.evaluation_id}`}
                            className="text-sm font-medium text-primary-600 hover:text-primary-700"
                          >
                            Evaluation {result.evaluation_id.slice(0, 8)}...
                          </Link>
                          <span
                            className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                              result.status === 'completed'
                                ? 'bg-green-100 text-green-800'
                                : 'bg-yellow-100 text-yellow-800'
                            }`}
                          >
                            {result.status}
                          </span>
                        </div>
                        {result.transcript && (
                          <p className="text-sm text-gray-700 mb-3 line-clamp-2">
                            {result.transcript}
                          </p>
                        )}
                        {result.metrics && Object.keys(result.metrics).length > 0 && (
                          <div className="flex flex-wrap gap-2">
                            {Object.entries(result.metrics).map(([key, value]) => (
                              <span
                                key={key}
                                className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800"
                              >
                                {key}: {typeof value === 'number' ? value.toFixed(4) : String(value)}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* Processing status */}
      {batch.status === 'processing' && (
        <div className="bg-orange-50 border border-orange-200 rounded-lg p-4">
          <div className="flex">
            <RefreshCw className="h-5 w-5 text-orange-400 animate-spin" />
            <div className="ml-3">
              <p className="text-sm text-orange-800">
                Processing {batch.processed_files} of {batch.total_files} files...
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

