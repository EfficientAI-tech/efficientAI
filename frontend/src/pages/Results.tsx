import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../lib/api'
import { Clock, CheckCircle, XCircle, Loader, Plus, X, Trash2, RefreshCw, AlertCircle } from 'lucide-react'
import { useState } from 'react'
import Button from '../components/Button'

interface EvaluatorResult {
  id: string
  result_id: string
  name: string
  timestamp: string
  duration_seconds: number | null
  status: 'queued' | 'call_initiating' | 'call_connecting' | 'call_in_progress' | 'call_ended' | 'transcribing' | 'evaluating' | 'completed' | 'failed'
  metric_scores: Record<string, { value: any; type: string; metric_name: string }> | null
  error_message: string | null
}

interface Metric {
  id: string
  name: string
  metric_type: 'number' | 'boolean' | 'rating'
  enabled: boolean
}

interface AudioFile {
  key: string
  filename: string
  size: number
  last_modified: string
}

interface Evaluator {
  id: string
  evaluator_id: string
  agent_id: string
  persona_id: string
  scenario_id: string
}

export default function Results() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [showManualModal, setShowManualModal] = useState(false)
  const [selectedAudioFile, setSelectedAudioFile] = useState<AudioFile | null>(null)
  const [selectedEvaluator, setSelectedEvaluator] = useState<string>('')
  const [selectedResults, setSelectedResults] = useState<Set<string>>(new Set())
  const [showDeleteModal, setShowDeleteModal] = useState(false)

  const { data: results = [], isLoading: loadingResults } = useQuery({
    queryKey: ['evaluator-results'],
    queryFn: () => apiClient.listEvaluatorResults(),
    refetchInterval: (query) => {
      // Poll if there are any in-progress results
      const data = query.state.data as any[]
      if (data && Array.isArray(data)) {
        const hasInProgress = data.some((result: any) => 
          result.status === 'queued' || 
          result.status === 'call_initiating' ||
          result.status === 'call_connecting' ||
          result.status === 'call_in_progress' ||
          result.status === 'call_ended' ||
          result.status === 'transcribing' || 
          result.status === 'evaluating'
        )
        return hasInProgress ? 3000 : false // Poll every 3 seconds if in-progress
      }
      return false
    },
  })

  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics'],
    queryFn: () => apiClient.listMetrics(),
  })

  // Fetch audio files from S3
  const { data: audioFiles } = useQuery({
    queryKey: ['manual-evaluations', 'audio-files'],
    queryFn: () => apiClient.listManualEvaluationAudioFiles(),
    enabled: showManualModal,
  })

  // Fetch evaluators
  const { data: evaluators = [] } = useQuery({
    queryKey: ['evaluators'],
    queryFn: () => apiClient.listEvaluators(),
    enabled: showManualModal,
  })

  // Create evaluator result mutation
  const createResultMutation = useMutation({
    mutationFn: (data: { evaluator_id: string; audio_s3_key: string; duration_seconds?: number }) =>
      apiClient.createEvaluatorResultManual(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
      setShowManualModal(false)
      setSelectedAudioFile(null)
      setSelectedEvaluator('')
    },
  })

  // Bulk delete mutation
  const deleteBulkMutation = useMutation({
    mutationFn: (ids: string[]) => apiClient.deleteEvaluatorResultsBulk(ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
      setSelectedResults(new Set())
    },
  })

  const handleSelectResult = (resultId: string, checked: boolean) => {
    const newSelected = new Set(selectedResults)
    if (checked) {
      newSelected.add(resultId)
    } else {
      newSelected.delete(resultId)
    }
    setSelectedResults(newSelected)
  }

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedResults(new Set(results.map((r: EvaluatorResult) => r.id)))
    } else {
      setSelectedResults(new Set())
    }
  }

  const handleDeleteSelected = () => {
    if (selectedResults.size === 0) return
    setShowDeleteModal(true)
  }

  const confirmDelete = () => {
    deleteBulkMutation.mutate(Array.from(selectedResults), {
      onSuccess: () => {
        setShowDeleteModal(false)
      }
    })
  }

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
      case 'queued':
      case 'call_initiating':
      case 'call_connecting':
        return <Clock className="w-4 h-4 text-gray-500" />
      case 'call_in_progress':
      case 'call_ended':
      case 'transcribing':
      case 'evaluating':
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
      case 'queued':
        return `${baseClasses} bg-gray-100 text-gray-800`
      case 'call_initiating':
        return `${baseClasses} bg-yellow-100 text-yellow-800`
      case 'call_connecting':
        return `${baseClasses} bg-orange-100 text-orange-800`
      case 'call_in_progress':
        return `${baseClasses} bg-blue-100 text-blue-800`
      case 'call_ended':
        return `${baseClasses} bg-indigo-100 text-indigo-800`
      case 'transcribing':
        return `${baseClasses} bg-blue-100 text-blue-800`
      case 'evaluating':
        return `${baseClasses} bg-purple-100 text-purple-800`
      default:
        return `${baseClasses} bg-gray-100 text-gray-800`
    }
  }
  
  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'call_initiating':
        return 'Initiating Call'
      case 'call_connecting':
        return 'Connecting'
      case 'call_in_progress':
        return 'Call In Progress'
      case 'call_ended':
        return 'Call Ended'
      case 'queued':
        return 'Queued'
      case 'transcribing':
        return 'Transcribing'
      case 'evaluating':
        return 'Evaluating'
      case 'completed':
        return 'Completed'
      case 'failed':
        return 'Failed'
      default:
        return status
    }
  }

  const formatMetricValue = (value: any, type: string, metricName?: string): React.ReactNode => {
    if (value === null || value === undefined) return 'N/A'
    
    // Special handling for Problem Resolution metric
    if (type === 'boolean' && metricName?.toLowerCase().includes('problem resolution')) {
      return value ? (
        <div className="flex items-center space-x-1 text-green-600">
          <CheckCircle className="w-4 h-4" />
          <span>Resolved</span>
        </div>
      ) : (
        <div className="flex items-center space-x-1 text-red-600">
          <AlertCircle className="w-4 h-4" />
          <span>Not Resolved</span>
        </div>
      )
    }
    
    if (type === 'boolean') return value ? 'Yes' : 'No'
    if (type === 'rating') return value?.toString() || 'N/A'
    if (type === 'number') return value?.toString() || 'N/A'
    return String(value)
  }

  const handleManualEvaluation = () => {
    if (!selectedAudioFile || !selectedEvaluator) {
      return
    }
    createResultMutation.mutate({
      evaluator_id: selectedEvaluator,
      audio_s3_key: selectedAudioFile.key,
    })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Results</h1>
          <p className="mt-2 text-sm text-gray-600">
            View evaluation results from running evaluators
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <Button
            variant="outline"
            onClick={() => queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })}
            disabled={loadingResults}
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${loadingResults ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          {selectedResults.size > 0 && (
            <div className="flex items-center space-x-2 bg-blue-50 border border-blue-200 rounded-lg px-4 py-2">
              <span className="text-sm font-medium text-blue-900">
                {selectedResults.size} selected
              </span>
              <button
                onClick={handleDeleteSelected}
                disabled={deleteBulkMutation.isPending}
                className="p-2 text-red-600 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="Delete selected"
              >
                <Trash2 className="w-5 h-5" />
              </button>
            </div>
          )}
          <Button onClick={() => setShowManualModal(true)}>
            <Plus className="w-4 h-4 mr-2" />
            Run Manual Evaluation
          </Button>
        </div>
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
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-12">
                    <input
                      type="checkbox"
                      checked={selectedResults.size === results.length && results.length > 0}
                      onChange={(e) => handleSelectAll(e.target.checked)}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      onClick={(e) => e.stopPropagation()}
                    />
                  </th>
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
                    <td className="px-6 py-4 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selectedResults.has(result.id)}
                        onChange={(e) => {
                          e.stopPropagation()
                          handleSelectResult(result.id, e.target.checked)
                        }}
                        className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                    </td>
                    <td 
                      className="px-6 py-4 whitespace-nowrap cursor-pointer"
                      onClick={() => navigate(`/results/${result.result_id}`)}
                    >
                      <span className="font-mono font-semibold text-sm text-blue-600 hover:text-blue-800 hover:underline">
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
                          {getStatusLabel(result.status)}
                        </span>
                      </div>
                    </td>
                    {enabledMetrics.map((metric: Metric) => {
                      const score = result.metric_scores?.[metric.id]
                      return (
                        <td key={metric.id} className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm text-gray-900">
                            {score ? formatMetricValue(score.value, score.type, score.metric_name) : 'N/A'}
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

      {/* Manual Evaluation Modal */}
      {showManualModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-gray-900">Run Manual Evaluation</h2>
                <button
                  onClick={() => {
                    setShowManualModal(false)
                    setSelectedAudioFile(null)
                    setSelectedEvaluator('')
                  }}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="w-6 h-6" />
                </button>
              </div>

              <div className="space-y-6">
                {/* Audio File Selection */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Select Audio File
                  </label>
                  <div className="border border-gray-300 rounded-lg max-h-64 overflow-y-auto">
                    {audioFiles?.files && audioFiles.files.length > 0 ? (
                      <div className="divide-y divide-gray-200">
                        {audioFiles.files.map((file: AudioFile) => (
                          <button
                            key={file.key}
                            onClick={() => setSelectedAudioFile(file)}
                            className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors ${
                              selectedAudioFile?.key === file.key
                                ? 'bg-primary-50 border-l-4 border-primary-500'
                                : ''
                            }`}
                          >
                            <div className="font-medium text-gray-900">{file.filename}</div>
                            <div className="text-sm text-gray-500">
                              {file.key} • {(file.size / 1024 / 1024).toFixed(2)} MB
                            </div>
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="p-8 text-center text-gray-500">
                        No audio files found
                      </div>
                    )}
                  </div>
                </div>

                {/* Evaluator Selection */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Select Evaluator
                  </label>
                  <select
                    value={selectedEvaluator}
                    onChange={(e) => setSelectedEvaluator(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  >
                    <option value="">Choose an evaluator...</option>
                    {evaluators.map((evaluator: Evaluator) => (
                      <option key={evaluator.id} value={evaluator.id}>
                        {evaluator.evaluator_id} - Agent: {evaluator.agent_id.substring(0, 8)}...
                      </option>
                    ))}
                  </select>
                </div>

                {/* Submit Button */}
                <div className="flex justify-end gap-3">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setShowManualModal(false)
                      setSelectedAudioFile(null)
                      setSelectedEvaluator('')
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={handleManualEvaluation}
                    disabled={!selectedAudioFile || !selectedEvaluator || createResultMutation.isPending}
                  >
                    {createResultMutation.isPending ? (
                      <>
                        <Loader className="w-4 h-4 animate-spin mr-2" />
                        Creating...
                      </>
                    ) : (
                      'Run Evaluation'
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowDeleteModal(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Confirm Delete</h3>
              <button
                onClick={() => setShowDeleteModal(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6">
              <p className="text-gray-700 mb-6">
                Are you sure you want to delete <span className="font-semibold">{selectedResults.size}</span> result(s)? 
                This action cannot be undone.
              </p>
              <div className="flex justify-end space-x-3">
                <Button
                  variant="outline"
                  onClick={() => setShowDeleteModal(false)}
                  disabled={deleteBulkMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={confirmDelete}
                  disabled={deleteBulkMutation.isPending}
                  isLoading={deleteBulkMutation.isPending}
                >
                  Delete
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

