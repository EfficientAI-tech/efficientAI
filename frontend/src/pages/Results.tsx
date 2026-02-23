import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../lib/api'
import { Clock, CheckCircle, XCircle, Loader, Plus, X, Trash2, RefreshCw, Eye, Activity, AlertTriangle, RotateCcw } from 'lucide-react'
import { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Button from '../components/Button'

interface EvaluatorResult {
  id: string
  result_id: string
  name: string
  evaluator_id: string | null
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
  name?: string | null
  agent_id?: string | null
  persona_id?: string | null
  scenario_id?: string | null
  custom_prompt?: string | null
}

export default function Results() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [showManualModal, setShowManualModal] = useState(false)
  const [selectedAudioFile, setSelectedAudioFile] = useState<AudioFile | null>(null)
  const [selectedEvaluator, setSelectedEvaluator] = useState<string>('')
  const [selectedResults, setSelectedResults] = useState<Set<string>>(new Set())
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [statusFilter, setStatusFilter] = useState<'all' | 'completed' | 'failed' | 'in_progress'>('all')

  const { data: results = [], isLoading: loadingResults } = useQuery({
    queryKey: ['evaluator-results'],
    queryFn: () => apiClient.listEvaluatorResults(),
    refetchInterval: (query) => {
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
        return hasInProgress ? 3000 : false
      }
      return false
    },
  })

  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics'],
    queryFn: () => apiClient.listMetrics(),
  })

  const { data: audioFiles } = useQuery({
    queryKey: ['manual-evaluations', 'audio-files'],
    queryFn: () => apiClient.listManualEvaluationAudioFiles(),
    enabled: showManualModal,
  })

  const { data: evaluators = [] } = useQuery({
    queryKey: ['evaluators'],
    queryFn: () => apiClient.listEvaluators(),
    enabled: showManualModal,
  })

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

  const deleteBulkMutation = useMutation({
    mutationFn: (ids: string[]) => apiClient.deleteEvaluatorResultsBulk(ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
      setSelectedResults(new Set())
    },
  })

  const [reEvaluatingIds, setReEvaluatingIds] = useState<Set<string>>(new Set())

  const reEvaluateMutation = useMutation({
    mutationFn: (id: string) => apiClient.reEvaluateResult(id),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
      setReEvaluatingIds(prev => { const s = new Set(prev); s.delete(id); return s })
    },
    onError: (_error, id) => {
      setReEvaluatingIds(prev => { const s = new Set(prev); s.delete(id); return s })
    },
  })

  // Summary statistics
  const summaryStats = useMemo(() => {
    const total = results.length
    const completed = results.filter((r: EvaluatorResult) => r.status === 'completed').length
    const failed = results.filter((r: EvaluatorResult) => r.status === 'failed').length
    const inProgress = results.filter((r: EvaluatorResult) => 
      ['queued', 'call_initiating', 'call_connecting', 'call_in_progress', 'call_ended', 'transcribing', 'evaluating'].includes(r.status)
    ).length
    const avgDuration = completed > 0
      ? results.filter((r: EvaluatorResult) => r.status === 'completed' && r.duration_seconds)
          .reduce((sum: number, r: EvaluatorResult) => sum + (r.duration_seconds || 0), 0) / completed
      : 0
    return { total, completed, failed, inProgress, avgDuration }
  }, [results])

  // Filter results by status
  const filteredResults = useMemo(() => {
    if (statusFilter === 'all') return results as EvaluatorResult[]
    if (statusFilter === 'completed') return (results as EvaluatorResult[]).filter(r => r.status === 'completed')
    if (statusFilter === 'failed') return (results as EvaluatorResult[]).filter(r => r.status === 'failed')
    // in_progress covers all active statuses
    return (results as EvaluatorResult[]).filter(r =>
      ['queued', 'call_initiating', 'call_connecting', 'call_in_progress', 'call_ended', 'transcribing', 'evaluating'].includes(r.status)
    )
  }, [results, statusFilter])

  const handleSelectResult = (resultId: string, checked: boolean) => {
    const newSelected = new Set(selectedResults)
    if (checked) {
      newSelected.add(resultId)
    } else {
      newSelected.delete(resultId)
    }
    setSelectedResults(newSelected)
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

  const COLUMN_METRICS = [
    'Follow Instructions',
    'Problem Resolution', 
    'Professionalism',
    'Clarity and Empathy'
  ]

  const hasValidValue = (value: any) => {
    if (value === null || value === undefined) return false
    if (value === '') return false
    if (typeof value === 'string' && value.toLowerCase() === 'n/a') return false
    if (typeof value === 'string' && value.toLowerCase() === 'na') return false
    if (typeof value === 'string' && value.trim() === '') return false
    return true
  }

  const enabledMetrics = metrics.filter((m: Metric) => m.enabled)
  
  const columnMetrics = enabledMetrics.filter((m: Metric) => {
    if (!COLUMN_METRICS.includes(m.name)) return false
    return results.some((result: EvaluatorResult) => {
      const score = result.metric_scores?.[m.id]
      return score && hasValidValue(score.value)
    })
  })

  const formatDuration = (seconds: number | null): string => {
    if (!seconds) return '--'
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const formatTimestamp = (timestamp: string): string => {
    const date = new Date(timestamp)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  const getStatusConfig = (status: string) => {
    switch (status) {
      case 'completed':
        return { dot: 'bg-emerald-500', bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200', label: 'Completed', icon: <CheckCircle className="w-3.5 h-3.5" /> }
      case 'failed':
        return { dot: 'bg-rose-500', bg: 'bg-rose-50', text: 'text-rose-700', border: 'border-rose-200', label: 'Failed', icon: <XCircle className="w-3.5 h-3.5" /> }
      case 'queued':
        return { dot: 'bg-slate-400', bg: 'bg-slate-50', text: 'text-slate-600', border: 'border-slate-200', label: 'Queued', icon: <Clock className="w-3.5 h-3.5" /> }
      case 'call_initiating':
        return { dot: 'bg-amber-500', bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', label: 'Initiating', icon: <Loader className="w-3.5 h-3.5 animate-spin" /> }
      case 'call_connecting':
        return { dot: 'bg-orange-500', bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200', label: 'Connecting', icon: <Loader className="w-3.5 h-3.5 animate-spin" /> }
      case 'call_in_progress':
        return { dot: 'bg-blue-500', bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200', label: 'In Call', icon: <Loader className="w-3.5 h-3.5 animate-spin" /> }
      case 'call_ended':
        return { dot: 'bg-indigo-500', bg: 'bg-indigo-50', text: 'text-indigo-700', border: 'border-indigo-200', label: 'Call Ended', icon: <Clock className="w-3.5 h-3.5" /> }
      case 'transcribing':
        return { dot: 'bg-cyan-500', bg: 'bg-cyan-50', text: 'text-cyan-700', border: 'border-cyan-200', label: 'Transcribing', icon: <Loader className="w-3.5 h-3.5 animate-spin" /> }
      case 'evaluating':
        return { dot: 'bg-purple-500', bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200', label: 'Evaluating', icon: <Loader className="w-3.5 h-3.5 animate-spin" /> }
      default:
        return { dot: 'bg-gray-400', bg: 'bg-gray-50', text: 'text-gray-600', border: 'border-gray-200', label: status, icon: null }
    }
  }

  const formatMetricValue = (value: any, type: string, metricName?: string): React.ReactNode => {
    if (value === null || value === undefined) return <span className="text-gray-300">--</span>
    
    const normalizedType = type?.toLowerCase()
    
    if (metricName === 'Emotion Category') {
      const emotion = String(value).toLowerCase()
      const emotionColors: Record<string, string> = {
        'neutral': 'bg-slate-100 text-slate-700',
        'happy': 'bg-emerald-100 text-emerald-700',
        'sad': 'bg-blue-100 text-blue-700',
        'angry': 'bg-rose-100 text-rose-700',
        'fearful': 'bg-purple-100 text-purple-700',
        'fear': 'bg-purple-100 text-purple-700',
        'surprised': 'bg-amber-100 text-amber-700',
        'surprise': 'bg-amber-100 text-amber-700',
        'calm': 'bg-teal-100 text-teal-700',
      }
      const colorClass = emotionColors[emotion] || 'bg-gray-100 text-gray-700'
      return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium ${colorClass}`}>
          {value}
        </span>
      )
    }
    
    if (normalizedType === 'boolean') {
      const boolValue = value === true || value === 1 || value === '1' || value === 'true'
      return boolValue ? (
        <span className="inline-flex items-center gap-1 text-emerald-600">
          <CheckCircle className="w-3.5 h-3.5" />
          <span className="text-xs font-medium">Yes</span>
        </span>
      ) : (
        <span className="inline-flex items-center gap-1 text-rose-600">
          <XCircle className="w-3.5 h-3.5" />
          <span className="text-xs font-medium">No</span>
        </span>
      )
    }
    
    if (normalizedType === 'rating') {
      if (typeof value === 'string' && isNaN(parseFloat(value))) {
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-purple-50 text-purple-700 text-xs font-medium capitalize">
            {value}
          </span>
        )
      }
      
      const numValue = typeof value === 'number' ? value : parseFloat(value)
      if (isNaN(numValue)) return <span className="text-gray-300">--</span>
      
      const normalizedValue = Math.max(0, Math.min(1, numValue))
      const percentage = Math.round(normalizedValue * 100)
      
      const getColor = (pct: number) => {
        if (pct >= 80) return { bar: 'bg-emerald-500', text: 'text-emerald-700' }
        if (pct >= 60) return { bar: 'bg-amber-500', text: 'text-amber-700' }
        return { bar: 'bg-rose-500', text: 'text-rose-700' }
      }
      
      const color = getColor(percentage)
      
      return (
        <div className="flex items-center gap-2.5 min-w-[120px]">
          <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <motion.div 
              className={`h-full rounded-full ${color.bar}`}
              initial={{ width: 0 }}
              animate={{ width: `${percentage}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            />
          </div>
          <span className={`text-xs font-semibold tabular-nums ${color.text}`}>{percentage}%</span>
        </div>
      )
    }
    
    if (normalizedType === 'number') {
      const numValue = typeof value === 'number' ? value : parseFloat(value)
      if (isNaN(numValue)) return <span className="text-gray-300">--</span>
      return <span className="text-sm font-semibold text-gray-900 tabular-nums">{numValue.toFixed(1)}</span>
    }
    
    return <span className="text-sm text-gray-700">{String(value)}</span>
  }

  const handleManualEvaluation = () => {
    if (!selectedAudioFile || !selectedEvaluator) return
    createResultMutation.mutate({
      evaluator_id: selectedEvaluator,
      audio_s3_key: selectedAudioFile.key,
    })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Evaluation Results</h1>
          <p className="mt-2 text-sm text-gray-600">
            Monitor and review evaluation outcomes across your voice agents
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            onClick={() => queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })}
            disabled={loadingResults}
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${loadingResults ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <AnimatePresence>
            {selectedResults.size > 0 && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
              >
                <Button
                  variant="danger"
                  onClick={handleDeleteSelected}
                  disabled={deleteBulkMutation.isPending}
                  isLoading={deleteBulkMutation.isPending}
                  leftIcon={!deleteBulkMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                >
                  Delete ({selectedResults.size})
                </Button>
              </motion.div>
            )}
          </AnimatePresence>
          <Button onClick={() => setShowManualModal(true)}>
            <Plus className="w-4 h-4 mr-2" />
            Run Manual Evaluation
          </Button>
        </div>
      </div>

      {/* Summary Stats */}
      {!loadingResults && results.length > 0 && (
        <motion.div
          className="grid grid-cols-2 md:grid-cols-4 gap-4"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Total</p>
                <p className="text-2xl font-bold text-gray-900 mt-1">{summaryStats.total}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center">
                <Activity className="w-5 h-5 text-slate-600" />
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Completed</p>
                <p className="text-2xl font-bold text-emerald-600 mt-1">{summaryStats.completed}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center">
                <CheckCircle className="w-5 h-5 text-emerald-500" />
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Failed</p>
                <p className="text-2xl font-bold text-rose-600 mt-1">{summaryStats.failed}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-rose-50 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-rose-500" />
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">In Progress</p>
                <p className="text-2xl font-bold text-blue-600 mt-1">{summaryStats.inProgress}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center">
                <Loader className={`w-5 h-5 text-blue-500 ${summaryStats.inProgress > 0 ? 'animate-spin' : ''}`} />
              </div>
            </div>
          </div>
        </motion.div>
      )}

      {/* Results Table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold text-gray-900">Results</h2>
            {results.length > 0 && (
              <div className="flex items-center gap-1">
                {([
                  { key: 'all' as const, label: 'All', count: summaryStats.total },
                  { key: 'completed' as const, label: 'Completed', count: summaryStats.completed },
                  { key: 'failed' as const, label: 'Failed', count: summaryStats.failed },
                  { key: 'in_progress' as const, label: 'In Progress', count: summaryStats.inProgress },
                ]).map(({ key, label, count }) => (
                  <button
                    key={key}
                    onClick={() => setStatusFilter(key)}
                    className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                      statusFilter === key
                        ? 'bg-primary-100 text-primary-800 border border-primary-300'
                        : 'text-gray-600 hover:bg-gray-100 border border-transparent'
                    }`}
                  >
                    {label} ({count})
                  </button>
                ))}
              </div>
            )}
          </div>
          {selectedResults.size > 0 && (
            <div className="text-sm text-gray-600">
              {selectedResults.size} selected
            </div>
          )}
        </div>
        {loadingResults ? (
          <div className="p-6 text-center text-gray-500">Loading...</div>
        ) : results.length === 0 ? (
          <div className="p-12 text-center">
            <p className="text-gray-500 mb-4">No results yet. Run an evaluator to see results here.</p>
          </div>
        ) : filteredResults.length === 0 ? (
          <div className="p-12 text-center">
            <p className="text-gray-500 mb-2">No {statusFilter === 'in_progress' ? 'in-progress' : statusFilter} results found.</p>
            <button
              onClick={() => setStatusFilter('all')}
              className="text-sm text-primary-600 hover:text-primary-800 font-medium"
            >
              Show all results
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-10">
                    <input
                      type="checkbox"
                      checked={selectedResults.size === filteredResults.length && filteredResults.length > 0}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedResults(new Set(filteredResults.map(r => r.id)))
                        } else {
                          setSelectedResults(new Set())
                        }
                      }}
                      className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      onClick={(e) => e.stopPropagation()}
                    />
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Result ID
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Name
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Timestamp
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Duration
                  </th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  {columnMetrics.map((metric: Metric) => (
                    <th
                      key={metric.id}
                      scope="col"
                      className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                    >
                      {metric.name}
                    </th>
                  ))}
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {filteredResults.map((result: EvaluatorResult) => {
                  const statusConfig = getStatusConfig(result.status)
                  const isSelected = selectedResults.has(result.id)
                  return (
                    <tr
                      key={result.id}
                      className={`hover:bg-gray-50 transition-colors cursor-pointer ${isSelected ? 'bg-blue-50' : ''}`}
                      onClick={() => navigate(`/results/${result.result_id}`)}
                    >
                      <td className="px-4 py-4 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={(e) => {
                            e.stopPropagation()
                            handleSelectResult(result.id, e.target.checked)
                          }}
                          className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                        />
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            navigate(`/results/${result.result_id}`)
                          }}
                          className="font-mono font-semibold text-primary-600 hover:text-primary-800 hover:underline cursor-pointer"
                        >
                          {result.result_id}
                        </button>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <span className="text-sm font-medium text-gray-900">{result.name}</span>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <span className="text-sm text-gray-500">{formatTimestamp(result.timestamp)}</span>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <div className="flex items-center text-sm text-gray-500">
                          <Clock className="w-4 h-4 mr-1" />
                          {formatDuration(result.duration_seconds)}
                        </div>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${statusConfig.bg} ${statusConfig.text} ${statusConfig.border}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${statusConfig.dot}`} />
                          {statusConfig.label}
                        </span>
                      </td>
                      {columnMetrics.map((metric: Metric) => {
                        const score = result.metric_scores?.[metric.id]
                        return (
                          <td key={metric.id} className="px-4 py-4 whitespace-nowrap">
                            <div className="text-sm text-gray-900">
                              {score ? formatMetricValue(score.value, score.type, score.metric_name) : <span className="text-gray-400">--</span>}
                            </div>
                          </td>
                        )
                      })}
                      <td className="px-4 py-4 whitespace-nowrap text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1">
                          {(result.status === 'completed' || result.status === 'failed') && result.evaluator_id && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setReEvaluatingIds(prev => new Set(prev).add(result.id))
                                reEvaluateMutation.mutate(result.id)
                              }}
                              disabled={reEvaluatingIds.has(result.id)}
                              leftIcon={<RotateCcw className={`w-3.5 h-3.5 ${reEvaluatingIds.has(result.id) ? 'animate-spin' : ''}`} />}
                            >
                              Re-evaluate
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => navigate(`/results/${result.result_id}`)}
                            leftIcon={<Eye className="w-4 h-4" />}
                          >
                            View
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Manual Evaluation Modal */}
      <AnimatePresence>
        {showManualModal && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div
              className="absolute inset-0 bg-black/40 backdrop-blur-sm"
              onClick={() => {
                setShowManualModal(false)
                setSelectedAudioFile(null)
                setSelectedEvaluator('')
              }}
            />
            <motion.div
              className="relative bg-white rounded-2xl shadow-2xl max-w-2xl w-full mx-4 max-h-[85vh] overflow-hidden"
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              transition={{ duration: 0.2 }}
            >
              <div className="px-6 py-5 border-b border-gray-100">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900">Run Manual Evaluation</h2>
                    <p className="text-sm text-gray-500 mt-0.5">Select an audio file and evaluator to begin</p>
                  </div>
                  <button
                    onClick={() => {
                      setShowManualModal(false)
                      setSelectedAudioFile(null)
                      setSelectedEvaluator('')
                    }}
                    className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="p-6 overflow-y-auto max-h-[60vh] space-y-6">
                {/* Audio File Selection */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Audio File
                  </label>
                  <div className="border border-gray-200 rounded-xl max-h-56 overflow-y-auto">
                    {audioFiles?.files && audioFiles.files.length > 0 ? (
                      <div className="divide-y divide-gray-100">
                        {audioFiles.files.map((file: AudioFile) => (
                          <button
                            key={file.key}
                            onClick={() => setSelectedAudioFile(file)}
                            className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors ${
                              selectedAudioFile?.key === file.key
                                ? 'bg-indigo-50 border-l-3 border-l-indigo-500'
                                : ''
                            }`}
                          >
                            <div className="text-sm font-medium text-gray-900">{file.filename}</div>
                            <div className="text-xs text-gray-500 mt-0.5">
                              {(file.size / 1024 / 1024).toFixed(2)} MB
                            </div>
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="p-8 text-center text-sm text-gray-500">
                        No audio files found
                      </div>
                    )}
                  </div>
                </div>

                {/* Evaluator Selection */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Evaluator
                  </label>
                  <select
                    value={selectedEvaluator}
                    onChange={(e) => setSelectedEvaluator(e.target.value)}
                    className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 bg-white"
                  >
                    <option value="">Choose an evaluator...</option>
                    {evaluators.map((evaluator: Evaluator) => (
                      <option key={evaluator.id} value={evaluator.id}>
                        {evaluator.evaluator_id} - {evaluator.custom_prompt
                          ? `Custom: ${evaluator.name || 'Unnamed'}`
                          : `Agent: ${evaluator.agent_id?.substring(0, 8) || '?'}...`
                        }
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Footer */}
              <div className="px-6 py-4 border-t border-gray-100 bg-gray-50/50 flex justify-end gap-3">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setShowManualModal(false)
                    setSelectedAudioFile(null)
                    setSelectedEvaluator('')
                  }}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={handleManualEvaluation}
                  disabled={!selectedAudioFile || !selectedEvaluator || createResultMutation.isPending}
                  isLoading={createResultMutation.isPending}
                >
                  {createResultMutation.isPending ? 'Creating...' : 'Run Evaluation'}
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Delete Confirmation Modal */}
      <AnimatePresence>
        {showDeleteModal && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div
              className="absolute inset-0 bg-black/40 backdrop-blur-sm"
              onClick={() => setShowDeleteModal(false)}
            />
            <motion.div
              className="relative bg-white rounded-2xl shadow-2xl max-w-md w-full mx-4"
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              transition={{ duration: 0.2 }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-6">
                <div className="w-12 h-12 rounded-full bg-rose-100 flex items-center justify-center mx-auto mb-4">
                  <Trash2 className="w-6 h-6 text-rose-600" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 text-center">Delete Results</h3>
                <p className="text-sm text-gray-500 text-center mt-2">
                  Are you sure you want to delete <span className="font-semibold text-gray-900">{selectedResults.size}</span> result{selectedResults.size !== 1 ? 's' : ''}? 
                  This action cannot be undone.
                </p>
              </div>
              <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowDeleteModal(false)}
                  disabled={deleteBulkMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={confirmDelete}
                  disabled={deleteBulkMutation.isPending}
                  isLoading={deleteBulkMutation.isPending}
                >
                  Delete
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
