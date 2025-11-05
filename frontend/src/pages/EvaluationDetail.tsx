import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { EvaluationStatus } from '../types/api'
import {
  ArrowLeft,
  Loader,
  CheckCircle,
  XCircle,
  Clock,
  AlertCircle,
  RefreshCw,
} from 'lucide-react'
import { format } from 'date-fns'

export default function EvaluationDetail() {
  const { id } = useParams<{ id: string }>()

  const { data: evaluation, isLoading: evalLoading } = useQuery({
    queryKey: ['evaluations', id],
    queryFn: () => apiClient.getEvaluation(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      // Poll if evaluation is pending or processing
      const data = query.state.data
      if (
        data?.status === EvaluationStatus.PENDING ||
        data?.status === EvaluationStatus.PROCESSING
      ) {
        return 3000 // Poll every 3 seconds
      }
      return false
    },
  })

  const { data: result, isLoading: resultLoading } = useQuery({
    queryKey: ['results', id],
    queryFn: () => apiClient.getEvaluationResult(id!),
    enabled: !!id && evaluation?.status === EvaluationStatus.COMPLETED,
  })

  if (evalLoading) {
    return (
      <div className="text-center py-12">
        <Loader className="h-8 w-8 animate-spin text-primary-600 mx-auto" />
      </div>
    )
  }

  if (!evaluation) {
    return (
      <div className="text-center py-12">
        <XCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
        <p className="text-gray-500">Evaluation not found</p>
        <Link to="/evaluations" className="mt-4 text-primary-600 hover:text-primary-700">
          ← Back to evaluations
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <Link
            to="/evaluations"
            className="text-gray-400 hover:text-gray-600"
          >
            <ArrowLeft className="h-6 w-6" />
          </Link>
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Evaluation Details</h1>
            <p className="mt-1 text-sm text-gray-600">
              ID: {evaluation.id}
            </p>
          </div>
        </div>
        <StatusBadge status={evaluation.status} />
      </div>

      {/* Evaluation Info */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Evaluation Information</h2>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-sm font-medium text-gray-500">Type</dt>
            <dd className="mt-1 text-sm text-gray-900">{evaluation.evaluation_type.toUpperCase()}</dd>
          </div>
          <div>
            <dt className="text-sm font-medium text-gray-500">Model</dt>
            <dd className="mt-1 text-sm text-gray-900">{evaluation.model_name || 'N/A'}</dd>
          </div>
          <div>
            <dt className="text-sm font-medium text-gray-500">Created</dt>
            <dd className="mt-1 text-sm text-gray-900">
              {format(new Date(evaluation.created_at), 'PPpp')}
            </dd>
          </div>
          {evaluation.started_at && (
            <div>
              <dt className="text-sm font-medium text-gray-500">Started</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {format(new Date(evaluation.started_at), 'PPpp')}
              </dd>
            </div>
          )}
          {evaluation.completed_at && (
            <div>
              <dt className="text-sm font-medium text-gray-500">Completed</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {format(new Date(evaluation.completed_at), 'PPpp')}
              </dd>
            </div>
          )}
          {evaluation.metrics_requested && evaluation.metrics_requested.length > 0 && (
            <div className="sm:col-span-2">
              <dt className="text-sm font-medium text-gray-500">Requested Metrics</dt>
              <dd className="mt-1 flex flex-wrap gap-2">
                {evaluation.metrics_requested.map((metric) => (
                  <span
                    key={metric}
                    className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-primary-100 text-primary-800"
                  >
                    {metric.toUpperCase()}
                  </span>
                ))}
              </dd>
            </div>
          )}
          {evaluation.reference_text && (
            <div className="sm:col-span-2">
              <dt className="text-sm font-medium text-gray-500">Reference Text</dt>
              <dd className="mt-1 text-sm text-gray-900">{evaluation.reference_text}</dd>
            </div>
          )}
          {evaluation.error_message && (
            <div className="sm:col-span-2">
              <dt className="text-sm font-medium text-red-500">Error</dt>
              <dd className="mt-1 text-sm text-red-600">{evaluation.error_message}</dd>
            </div>
          )}
        </dl>
      </div>

      {/* Results */}
      {evaluation.status === EvaluationStatus.COMPLETED && (
        <>
          {resultLoading ? (
            <div className="text-center py-8">
              <Loader className="h-6 w-6 animate-spin text-primary-600 mx-auto" />
            </div>
          ) : result ? (
            <>
              {/* Transcript */}
              {result.transcript && (
                <div className="bg-white shadow rounded-lg p-6">
                  <h2 className="text-lg font-medium text-gray-900 mb-4">Transcript</h2>
                  <p className="text-gray-700 whitespace-pre-wrap">{result.transcript}</p>
                </div>
              )}

              {/* Metrics */}
              {Object.keys(result.metrics).length > 0 && (
                <div className="bg-white shadow rounded-lg p-6">
                  <h2 className="text-lg font-medium text-gray-900 mb-4">Metrics</h2>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {Object.entries(result.metrics).map(([key, value]) => (
                      <div key={key} className="bg-gray-50 rounded-lg p-4">
                        <dt className="text-sm font-medium text-gray-500 uppercase">
                          {key.replace(/_/g, ' ')}
                        </dt>
                        <dd className="mt-1 text-2xl font-semibold text-gray-900">
                          {typeof value === 'number'
                            ? value.toFixed(4)
                            : String(value)}
                        </dd>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Processing Info */}
              {(result.processing_time !== null || result.model_used) && (
                <div className="bg-white shadow rounded-lg p-6">
                  <h2 className="text-lg font-medium text-gray-900 mb-4">Processing Information</h2>
                  <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    {result.processing_time !== null && result.processing_time !== undefined && (
                      <div>
                        <dt className="text-sm font-medium text-gray-500">Processing Time</dt>
                        <dd className="mt-1 text-sm text-gray-900">
                          {(result.processing_time / 1000).toFixed(2)}s
                        </dd>
                      </div>
                    )}
                    {result.model_used && (
                      <div>
                        <dt className="text-sm font-medium text-gray-500">Model Used</dt>
                        <dd className="mt-1 text-sm text-gray-900">{result.model_used}</dd>
                      </div>
                    )}
                  </dl>
                </div>
              )}
            </>
          ) : null}
        </>
      )}

      {/* Status messages */}
      {evaluation.status === EvaluationStatus.PENDING && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="flex">
            <Clock className="h-5 w-5 text-yellow-400" />
            <div className="ml-3">
              <p className="text-sm text-yellow-800">
                This evaluation is pending and will be processed shortly.
              </p>
            </div>
          </div>
        </div>
      )}

      {evaluation.status === EvaluationStatus.PROCESSING && (
        <div className="bg-orange-50 border border-orange-200 rounded-lg p-4">
          <div className="flex">
            <RefreshCw className="h-5 w-5 text-orange-400 animate-spin" />
            <div className="ml-3">
              <p className="text-sm text-orange-800">
                This evaluation is currently being processed...
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: EvaluationStatus }) {
  const statusConfig = {
    [EvaluationStatus.PENDING]: {
      bg: 'bg-yellow-100',
      text: 'text-yellow-800',
      label: 'Pending',
      icon: Clock,
    },
    [EvaluationStatus.PROCESSING]: {
      bg: 'bg-orange-100',
      text: 'text-orange-800',
      label: 'Processing',
      icon: Loader,
    },
    [EvaluationStatus.COMPLETED]: {
      bg: 'bg-green-100',
      text: 'text-green-800',
      label: 'Completed',
      icon: CheckCircle,
    },
    [EvaluationStatus.FAILED]: {
      bg: 'bg-red-100',
      text: 'text-red-800',
      label: 'Failed',
      icon: XCircle,
    },
    [EvaluationStatus.CANCELLED]: {
      bg: 'bg-gray-100',
      text: 'text-gray-800',
      label: 'Cancelled',
      icon: AlertCircle,
    },
  }

  const config = statusConfig[status]
  const Icon = config.icon

  return (
    <span
      className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${config.bg} ${config.text}`}
    >
      <Icon className={`h-4 w-4 mr-2 ${status === EvaluationStatus.PROCESSING ? 'animate-spin' : ''}`} />
      {config.label}
    </span>
  )
}

