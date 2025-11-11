import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { apiClient } from '../lib/api'
import { EvaluationStatus, Evaluation, MessageResponse } from '../types/api'
import {
  Plus,
  Loader,
  FileCheck,
  Filter,
  CheckCircle,
  Clock,
  XCircle,
  AlertCircle,
  Mic,
  List,
} from 'lucide-react'
import { format } from 'date-fns'
import CreateEvaluationModal from '../components/CreateEvaluationModal'
import ManualEvaluations from '../components/ManualEvaluations'
import ManualEvaluationsList from '../components/ManualEvaluationsList'
import Button from '../components/Button'

export default function Evaluations() {
  const [searchParams, setSearchParams] = useSearchParams()
  const statusFilter = searchParams.get('status') as EvaluationStatus | null
  const tabParam = searchParams.get('tab')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [activeTab, setActiveTab] = useState<'evaluations' | 'manual'>(
    (tabParam === 'manual' ? 'manual' : 'evaluations') as 'evaluations' | 'manual'
  )
  const [showTranscriptionForm, setShowTranscriptionForm] = useState(false)
  const queryClient = useQueryClient()

  const { data: evaluations, isLoading } = useQuery({
    queryKey: ['evaluations', 'list', statusFilter],
    queryFn: () => apiClient.listEvaluations(0, 100, statusFilter || undefined),
  })

  const deleteMutation = useMutation<MessageResponse, Error, string>({
    mutationFn: (evaluationId: string) => apiClient.deleteEvaluation(evaluationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluations'] })
    },
  })

  const cancelMutation = useMutation<MessageResponse, Error, string>({
    mutationFn: (evaluationId: string) => apiClient.cancelEvaluation(evaluationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluations'] })
    },
  })

  const handleDelete = async (evaluationId: string) => {
    if (confirm('Are you sure you want to delete this evaluation?')) {
      try {
        await deleteMutation.mutateAsync(evaluationId)
      } catch (error) {
        // Error handled
      }
    }
  }

  const handleCancel = async (evaluationId: string) => {
    if (confirm('Are you sure you want to cancel this evaluation?')) {
      try {
        await cancelMutation.mutateAsync(evaluationId)
      } catch (error) {
        // Error handled
      }
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Evaluations</h1>
          <p className="mt-2 text-sm text-gray-600">
            Manage and monitor your ASR evaluations
          </p>
        </div>
        {activeTab === 'evaluations' && (
          <Button
            variant="primary"
            onClick={() => setShowCreateModal(true)}
            leftIcon={<Plus className="h-4 w-4" />}
          >
            New Evaluation
          </Button>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => {
              setActiveTab('evaluations')
              setSearchParams({})
            }}
            className={`${
              activeTab === 'evaluations'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2`}
          >
            <List className="h-4 w-4" />
            <span>Automated Evaluations</span>
          </button>
          <button
            onClick={() => {
              setActiveTab('manual')
              setSearchParams({ tab: 'manual' })
            }}
            className={`${
              activeTab === 'manual'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm flex items-center space-x-2`}
          >
            <Mic className="h-4 w-4" />
            <span>Manual Evaluations</span>
          </button>
        </nav>
      </div>

      {activeTab === 'manual' ? (
        showTranscriptionForm ? (
          <ManualEvaluations onBack={() => setShowTranscriptionForm(false)} />
        ) : (
          <ManualEvaluationsList onNewTranscription={() => setShowTranscriptionForm(true)} />
        )
      ) : (
        <>

      {/* Filters */}
      <div className="bg-white shadow rounded-lg p-4">
        <div className="flex items-center space-x-2">
          <Filter className="h-5 w-5 text-gray-400" />
          <span className="text-sm font-medium text-gray-700">Filter by status:</span>
          <div className="flex space-x-2 ml-4">
            <button
              onClick={() => setSearchParams({})}
              className={`px-3 py-1 text-sm rounded-md ${
                !statusFilter
                  ? 'bg-primary-100 text-primary-700'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              All
            </button>
            {Object.values(EvaluationStatus).map((status) => (
              <button
                key={status}
                onClick={() => setSearchParams({ status })}
                className={`px-3 py-1 text-sm rounded-md ${
                  statusFilter === status
                    ? 'bg-primary-100 text-primary-700'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                {status.charAt(0).toUpperCase() + status.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Evaluations List */}
      {isLoading ? (
        <div className="text-center py-12">
          <Loader className="h-8 w-8 animate-spin text-primary-600 mx-auto" />
        </div>
      ) : !evaluations || evaluations.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <FileCheck className="h-12 w-12 mx-auto mb-4 text-gray-400" />
          <p className="text-gray-500">No evaluations found</p>
          <Button
            variant="ghost"
            onClick={() => setShowCreateModal(true)}
            className="mt-4"
          >
            Create your first evaluation →
          </Button>
        </div>
      ) : (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <ul className="divide-y divide-gray-200">
            {evaluations.map((evaluation: Evaluation) => (
              <li key={evaluation.id}>
                <Link
                  to={`/evaluations/${evaluation.id}`}
                  className="block hover:bg-gray-50 transition-colors"
                >
                  <div className="px-4 py-4 sm:px-6">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center">
                        <StatusIcon status={evaluation.status} />
                        <div className="ml-4">
                          <p className="text-sm font-medium text-gray-900">
                            {evaluation.evaluation_type.toUpperCase()} Evaluation
                          </p>
                          <div className="mt-1 flex items-center text-sm text-gray-500 space-x-4">
                            <span>ID: {evaluation.id.slice(0, 8)}...</span>
                            <span>•</span>
                            <span>{format(new Date(evaluation.created_at), 'MMM d, yyyy HH:mm')}</span>
                            {evaluation.model_name && (
                              <>
                                <span>•</span>
                                <span>Model: {evaluation.model_name}</span>
                              </>
                            )}
                          </div>
                          {evaluation.metrics_requested && evaluation.metrics_requested.length > 0 && (
                            <div className="mt-2 flex flex-wrap gap-2">
                              {evaluation.metrics_requested.map((metric: string) => (
                                <span
                                  key={metric}
                                  className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800"
                                >
                                  {metric.toUpperCase()}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center space-x-2">
                        <StatusBadge status={evaluation.status} />
                        {(evaluation.status === EvaluationStatus.PENDING ||
                          evaluation.status === EvaluationStatus.PROCESSING) && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.preventDefault()
                              e.stopPropagation()
                              handleCancel(evaluation.id)
                            }}
                            className="text-red-700 hover:bg-red-100 hover:text-red-800"
                          >
                            Cancel
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()
                            handleDelete(evaluation.id)
                          }}
                          className="text-red-700 hover:bg-red-100 hover:text-red-800"
                        >
                          Delete
                        </Button>
                      </div>
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

          {showCreateModal && (
            <CreateEvaluationModal
              isOpen={showCreateModal}
              onClose={() => setShowCreateModal(false)}
            />
          )}
        </>
      )}
    </div>
  )
}

function StatusIcon({ status }: { status: EvaluationStatus }) {
  const iconConfig = {
    [EvaluationStatus.PENDING]: { Icon: Clock, color: 'text-yellow-500' },
    [EvaluationStatus.PROCESSING]: { Icon: Loader, color: 'text-orange-500 animate-spin' },
    [EvaluationStatus.COMPLETED]: { Icon: CheckCircle, color: 'text-green-500' },
    [EvaluationStatus.FAILED]: { Icon: XCircle, color: 'text-red-500' },
    [EvaluationStatus.CANCELLED]: { Icon: AlertCircle, color: 'text-gray-500' },
  }

  const { Icon, color } = iconConfig[status]
  return <Icon className={`h-5 w-5 ${color}`} />
}

function StatusBadge({ status }: { status: EvaluationStatus }) {
  const statusConfig = {
    [EvaluationStatus.PENDING]: {
      bg: 'bg-yellow-100',
      text: 'text-yellow-800',
      label: 'Pending',
    },
    [EvaluationStatus.PROCESSING]: {
      bg: 'bg-orange-100',
      text: 'text-orange-800',
      label: 'Processing',
    },
    [EvaluationStatus.COMPLETED]: {
      bg: 'bg-green-100',
      text: 'text-green-800',
      label: 'Completed',
    },
    [EvaluationStatus.FAILED]: {
      bg: 'bg-red-100',
      text: 'text-red-800',
      label: 'Failed',
    },
    [EvaluationStatus.CANCELLED]: {
      bg: 'bg-gray-100',
      text: 'text-gray-800',
      label: 'Cancelled',
    },
  }

  const config = statusConfig[status]

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${config.bg} ${config.text}`}
    >
      {config.label}
    </span>
  )
}

