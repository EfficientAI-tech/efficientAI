import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import ReactMarkdown from 'react-markdown'
import {
  Sparkles,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  ArrowUpRight,
  Check,
  Upload,
  Eye,
  X,
  Trash2,
  Columns2,
  FileText,
} from 'lucide-react'
import { format } from 'date-fns'

interface OptimizationRun {
  id: string
  agent_id: string
  evaluator_id: string | null
  voice_bundle_id: string | null
  seed_prompt: string
  best_prompt: string | null
  best_score: number | null
  status: string
  config: Record<string, any> | null
  metric_history: Array<{ score: number; batch_size: number }> | null
  num_iterations: number | null
  num_metric_calls: number | null
  error_message: string | null
  created_at: string
  updated_at: string
}

interface Candidate {
  id: string
  optimization_run_id: string
  prompt_text: string
  score: number | null
  metric_breakdown: Record<string, any> | null
  reflection_summary: string | null
  parent_candidate_id: string | null
  is_accepted: boolean
  pushed_to_provider_at: string | null
  created_at: string
}

interface Agent {
  id: string
  name: string
  description: string | null
  voice_bundle_id: string | null
  voice_ai_integration_id: string | null
  voice_ai_agent_id: string | null
}

interface Evaluator {
  id: string
  evaluator_id: string
  name: string | null
  agent_id: string | null
}

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: typeof Clock }> = {
  pending: { label: 'Pending', color: 'bg-gray-100 text-gray-700', icon: Clock },
  running: { label: 'Running', color: 'bg-blue-100 text-blue-700', icon: Loader2 },
  completed: { label: 'Completed', color: 'bg-green-100 text-green-700', icon: CheckCircle2 },
  failed: { label: 'Failed', color: 'bg-red-100 text-red-700', icon: XCircle },
}

const PROSE_CLASSES =
  'prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100'

export default function PromptOptimization() {
  const queryClient = useQueryClient()
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [showNewRunDialog, setShowNewRunDialog] = useState(false)
  const [newRunAgentId, setNewRunAgentId] = useState('')
  const [newRunEvaluatorId, setNewRunEvaluatorId] = useState('')
  const [compareCandidateId, setCompareCandidateId] = useState<string | null>(null)
  const [showPromptDiff, setShowPromptDiff] = useState<string | null>(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)

  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  const { data: evaluators = [] } = useQuery<Evaluator[]>({
    queryKey: ['evaluators'],
    queryFn: () => apiClient.listEvaluators(),
  })

  const { data: runs = [], isLoading: runsLoading } = useQuery<OptimizationRun[]>({
    queryKey: ['optimization-runs'],
    queryFn: () => apiClient.listOptimizationRuns(),
    refetchInterval: 5000,
  })

  const { data: candidates = [] } = useQuery<Candidate[]>({
    queryKey: ['optimization-candidates', selectedRunId],
    queryFn: () => apiClient.listOptimizationCandidates(selectedRunId!),
    enabled: !!selectedRunId,
  })

  const selectedRun = runs.find(r => r.id === selectedRunId)
  const compareCandidate = candidates.find(c => c.id === compareCandidateId)

  const createRunMutation = useMutation({
    mutationFn: (data: { agent_id: string; evaluator_id?: string }) =>
      apiClient.createOptimizationRun(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['optimization-runs'] })
      setShowNewRunDialog(false)
      setNewRunAgentId('')
      setNewRunEvaluatorId('')
    },
  })

  const deleteRunMutation = useMutation({
    mutationFn: (runId: string) => apiClient.deleteOptimizationRun(runId),
    onSuccess: (_data, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['optimization-runs'] })
      if (selectedRunId === deletedId) {
        setSelectedRunId(null)
        setCompareCandidateId(null)
      }
      setDeleteConfirmId(null)
    },
  })

  const acceptMutation = useMutation({
    mutationFn: ({ runId, candidateId }: { runId: string; candidateId: string }) =>
      apiClient.acceptCandidate(runId, candidateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['optimization-candidates', selectedRunId] })
    },
  })

  const pushMutation = useMutation({
    mutationFn: ({ runId, candidateId }: { runId: string; candidateId: string }) =>
      apiClient.pushCandidateToProvider(runId, candidateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['optimization-candidates', selectedRunId] })
      queryClient.invalidateQueries({ queryKey: ['optimization-runs'] })
    },
  })

  const getAgentName = (agentId: string) =>
    agents.find(a => a.id === agentId)?.name || 'Unknown Agent'

  return (
    <div className="h-[calc(100vh-7rem)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Sparkles className="h-6 w-6 text-purple-600" />
            GEPA Prompt Optimization
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Self-improving voice agents via reflective prompt evolution
          </p>
        </div>
        <button
          onClick={() => setShowNewRunDialog(true)}
          className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 transition-colors"
        >
          <Play className="h-4 w-4" />
          New Optimization Run
        </button>
      </div>

      {/* Main Content - Full-width Split View */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Left Panel - Runs List */}
        <div className="w-80 flex-shrink-0 flex flex-col bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 bg-gray-50/50">
            <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
              <Sparkles className="h-3.5 w-3.5 text-purple-500" />
              Optimization Runs
            </h2>
          </div>
          <div className="flex-1 overflow-y-auto">
            {runsLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
              </div>
            ) : runs.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 px-4 text-center">
                <Sparkles className="h-10 w-10 text-gray-200 mb-3" />
                <p className="text-sm text-gray-500">No optimization runs yet</p>
                <button
                  onClick={() => setShowNewRunDialog(true)}
                  className="mt-3 text-sm text-purple-600 font-medium hover:text-purple-700"
                >
                  Start your first run
                </button>
              </div>
            ) : (
              runs.map(run => {
                const status = STATUS_CONFIG[run.status] || STATUS_CONFIG.pending
                const StatusIcon = status.icon
                const isSelected = selectedRunId === run.id
                return (
                  <button
                    key={run.id}
                    className={`group w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors ${
                      isSelected
                        ? 'bg-purple-50/60 border-l-4 border-l-purple-600'
                        : 'border-l-4 border-l-transparent'
                    }`}
                    onClick={() => {
                      setSelectedRunId(run.id)
                      setCompareCandidateId(null)
                    }}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-900 truncate">
                          {getAgentName(run.agent_id)}
                        </p>
                        <div className="flex items-center gap-2 mt-1.5">
                          <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-xs font-medium ${status.color}`}>
                            <StatusIcon className={`h-3 w-3 ${run.status === 'running' ? 'animate-spin' : ''}`} />
                            {status.label}
                          </span>
                          {run.best_score != null && (
                            <span className="text-xs text-green-600 font-medium">
                              {(run.best_score * 100).toFixed(1)}%
                            </span>
                          )}
                        </div>
                        <span className="text-xs text-gray-400 mt-1 block">
                          {format(new Date(run.created_at), 'MMM d, HH:mm')}
                        </span>
                      </div>
                      <button
                        onClick={e => {
                          e.stopPropagation()
                          setDeleteConfirmId(run.id)
                        }}
                        className="p-1 text-gray-300 hover:text-red-500 rounded-md hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-all flex-shrink-0 mt-0.5"
                        title="Delete run"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </button>
                )
              })
            )}
          </div>
        </div>

        {/* Right Panel - Detail & Comparison */}
        <div className="flex-1 flex flex-col bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          {selectedRun ? (
            <>
              {/* Run Info Header */}
              <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 bg-gray-50/50 flex-shrink-0">
                <div className="flex items-center gap-4 min-w-0">
                  <h3 className="text-lg font-semibold text-gray-900 truncate">
                    {getAgentName(selectedRun.agent_id)}
                  </h3>
                  <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium flex-shrink-0 ${STATUS_CONFIG[selectedRun.status]?.color || ''}`}>
                    {STATUS_CONFIG[selectedRun.status]?.label || selectedRun.status}
                  </span>
                </div>
                <div className="flex items-center gap-6 text-sm flex-shrink-0">
                  <div className="text-center">
                    <span className="text-gray-400 text-xs block">Best Score</span>
                    <span className="font-semibold text-gray-900">
                      {selectedRun.best_score != null
                        ? `${(selectedRun.best_score * 100).toFixed(1)}%`
                        : '--'}
                    </span>
                  </div>
                  <div className="text-center">
                    <span className="text-gray-400 text-xs block">Metric Calls</span>
                    <span className="font-semibold text-gray-900">
                      {selectedRun.num_metric_calls ?? '--'}
                    </span>
                  </div>
                  <div className="text-center">
                    <span className="text-gray-400 text-xs block">Created</span>
                    <span className="font-medium text-gray-700 text-xs">
                      {format(new Date(selectedRun.created_at), 'MMM d, yyyy HH:mm')}
                    </span>
                  </div>
                  {selectedRun.metric_history && selectedRun.metric_history.length > 0 && (
                    <div className="flex items-end gap-0.5 h-8 pl-4 border-l border-gray-200" title="Score progression">
                      {selectedRun.metric_history.map((entry, i) => (
                        <div
                          key={i}
                          className="w-1.5 bg-purple-300 rounded-t transition-all hover:bg-purple-500"
                          style={{ height: `${Math.max(entry.score * 100, 8)}%` }}
                          title={`Iteration ${i + 1}: ${(entry.score * 100).toFixed(1)}%`}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {selectedRun.error_message && (
                <div className="mx-6 mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex-shrink-0">
                  {selectedRun.error_message}
                </div>
              )}

              {/* Content Area */}
              <div className="flex-1 flex min-h-0">
                {/* Main Prompt Comparison / Content */}
                <div className="flex-1 overflow-y-auto">
                  {compareCandidateId && compareCandidate ? (
                    /* Full-width Side-by-Side Comparison */
                    <div className="p-6 h-full flex flex-col">
                      <div className="flex items-center justify-between mb-4 flex-shrink-0">
                        <div className="flex items-center gap-2">
                          <Columns2 className="h-4 w-4 text-purple-500" />
                          <span className="text-sm font-semibold text-gray-700">
                            Seed vs Optimized Comparison
                          </span>
                          {compareCandidate.score != null && (
                            <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full font-medium">
                              Score: {(compareCandidate.score * 100).toFixed(1)}%
                            </span>
                          )}
                        </div>
                        <button
                          onClick={() => setCompareCandidateId(null)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 hover:text-gray-800 rounded-lg hover:bg-gray-100 transition-colors"
                        >
                          <X className="h-3.5 w-3.5" />
                          Close comparison
                        </button>
                      </div>
                      <div className="grid grid-cols-2 gap-6 flex-1 min-h-0">
                        <div className="flex flex-col min-h-0">
                          <div className="text-xs font-medium text-gray-500 mb-2 flex items-center gap-1.5 flex-shrink-0">
                            <span className="inline-block w-2 h-2 rounded-full bg-gray-400" />
                            Seed Prompt (Original)
                          </div>
                          <div className={`flex-1 bg-gray-50 border border-gray-200 rounded-lg p-5 overflow-y-auto ${PROSE_CLASSES}`}>
                            <ReactMarkdown>{selectedRun.seed_prompt}</ReactMarkdown>
                          </div>
                        </div>
                        <div className="flex flex-col min-h-0">
                          <div className="text-xs font-medium text-gray-500 mb-2 flex items-center gap-1.5 flex-shrink-0">
                            <span className="inline-block w-2 h-2 rounded-full bg-purple-500" />
                            Optimized Candidate
                            {compareCandidate.score != null && (
                              <span className="ml-1 text-purple-600 font-medium">
                                ({(compareCandidate.score * 100).toFixed(1)}%)
                              </span>
                            )}
                          </div>
                          <div className={`flex-1 bg-purple-50 border border-purple-200 rounded-lg p-5 overflow-y-auto ${PROSE_CLASSES}`}>
                            <ReactMarkdown>{compareCandidate.prompt_text}</ReactMarkdown>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    /* Seed Prompt + Candidates */
                    <div className="p-6 space-y-5">
                      {/* Seed Prompt */}
                      <div>
                        <h4 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
                          <FileText className="h-4 w-4 text-gray-400" />
                          Seed Prompt (Original)
                        </h4>
                        <div className={`bg-gray-50 border border-gray-200 rounded-lg p-4 max-h-52 overflow-y-auto ${PROSE_CLASSES}`}>
                          <ReactMarkdown>{selectedRun.seed_prompt}</ReactMarkdown>
                        </div>
                      </div>

                      {/* Candidates */}
                      <div>
                        <h4 className="text-sm font-semibold text-gray-700 mb-3">
                          Optimized Candidates ({candidates.length})
                        </h4>
                        {candidates.length === 0 ? (
                          <p className="text-sm text-gray-400 text-center py-6">
                            {selectedRun.status === 'running'
                              ? 'Optimization in progress...'
                              : 'No candidates generated'}
                          </p>
                        ) : (
                          <div className="space-y-3">
                            {candidates.map((candidate, idx) => (
                              <div
                                key={candidate.id}
                                className={`border rounded-lg p-4 transition-colors ${
                                  candidate.is_accepted
                                    ? 'border-green-300 bg-green-50'
                                    : compareCandidateId === candidate.id
                                      ? 'border-purple-300 bg-purple-50/30'
                                      : 'border-gray-200 hover:border-gray-300'
                                }`}
                              >
                                <div className="flex items-center justify-between mb-2">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-sm font-medium text-gray-900">
                                      Candidate #{idx + 1}
                                    </span>
                                    {candidate.score != null && (
                                      <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full font-medium">
                                        {(candidate.score * 100).toFixed(1)}%
                                      </span>
                                    )}
                                    {candidate.is_accepted && (
                                      <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium flex items-center gap-1">
                                        <Check className="h-3 w-3" /> Accepted
                                      </span>
                                    )}
                                    {candidate.pushed_to_provider_at && (
                                      <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium flex items-center gap-1">
                                        <Upload className="h-3 w-3" /> Pushed
                                      </span>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-1">
                                    <button
                                      onClick={() =>
                                        setCompareCandidateId(
                                          compareCandidateId === candidate.id ? null : candidate.id
                                        )
                                      }
                                      className={`p-1.5 rounded-md transition-colors ${
                                        compareCandidateId === candidate.id
                                          ? 'text-purple-600 bg-purple-100'
                                          : 'text-gray-400 hover:text-purple-600 hover:bg-purple-50'
                                      }`}
                                      title="Compare side-by-side with seed"
                                    >
                                      <Columns2 className="h-4 w-4" />
                                    </button>
                                    <button
                                      onClick={() =>
                                        setShowPromptDiff(
                                          showPromptDiff === candidate.id ? null : candidate.id
                                        )
                                      }
                                      className={`p-1.5 rounded-md transition-colors ${
                                        showPromptDiff === candidate.id
                                          ? 'text-gray-700 bg-gray-100'
                                          : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
                                      }`}
                                      title="View prompt"
                                    >
                                      <Eye className="h-4 w-4" />
                                    </button>
                                    {!candidate.is_accepted && (
                                      <button
                                        onClick={() =>
                                          acceptMutation.mutate({
                                            runId: selectedRun.id,
                                            candidateId: candidate.id,
                                          })
                                        }
                                        disabled={acceptMutation.isPending}
                                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-green-700 bg-green-50 rounded-md hover:bg-green-100 border border-green-200"
                                      >
                                        <Check className="h-3 w-3" /> Accept
                                      </button>
                                    )}
                                    {candidate.is_accepted && !candidate.pushed_to_provider_at && (
                                      <button
                                        onClick={() =>
                                          pushMutation.mutate({
                                            runId: selectedRun.id,
                                            candidateId: candidate.id,
                                          })
                                        }
                                        disabled={pushMutation.isPending}
                                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-blue-700 bg-blue-50 rounded-md hover:bg-blue-100 border border-blue-200"
                                      >
                                        {pushMutation.isPending ? (
                                          <Loader2 className="h-3 w-3 animate-spin" />
                                        ) : (
                                          <ArrowUpRight className="h-3 w-3" />
                                        )}
                                        Push to Provider
                                      </button>
                                    )}
                                  </div>
                                </div>

                                {candidate.reflection_summary && (
                                  <p className="text-xs text-gray-500 italic mb-2">
                                    {candidate.reflection_summary}
                                  </p>
                                )}

                                {showPromptDiff === candidate.id && (
                                  <div className={`mt-3 bg-gray-50 rounded-lg p-4 max-h-52 overflow-y-auto border border-gray-200 ${PROSE_CLASSES}`}>
                                    <ReactMarkdown>{candidate.prompt_text}</ReactMarkdown>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Candidates Sidebar (visible during comparison) */}
                {compareCandidateId && compareCandidate && candidates.length > 0 && (
                  <div className="w-64 flex-shrink-0 border-l border-gray-200 flex flex-col overflow-hidden bg-gray-50/30">
                    <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                      <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
                        Candidates ({candidates.length})
                      </h4>
                    </div>
                    <div className="flex-1 overflow-y-auto">
                      {candidates.map((candidate, idx) => (
                        <button
                          key={candidate.id}
                          onClick={() => setCompareCandidateId(candidate.id)}
                          className={`w-full text-left px-4 py-3 border-b border-gray-100 transition-colors ${
                            compareCandidateId === candidate.id
                              ? 'bg-purple-50 border-l-4 border-l-purple-500'
                              : 'hover:bg-gray-50 border-l-4 border-l-transparent'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-medium text-gray-900">#{idx + 1}</span>
                            <div className="flex items-center gap-1.5">
                              {candidate.score != null && (
                                <span className="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded-full font-medium">
                                  {(candidate.score * 100).toFixed(1)}%
                                </span>
                              )}
                              {candidate.is_accepted && (
                                <Check className="h-3 w-3 text-green-600" />
                              )}
                            </div>
                          </div>
                          {candidate.reflection_summary && (
                            <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                              {candidate.reflection_summary}
                            </p>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
              <Sparkles className="h-16 w-16 text-gray-200 mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-1">Select an optimization run</h3>
              <p className="text-sm text-gray-500 max-w-sm">
                Choose a run from the list to view its candidates, compare prompts, and push optimized results to your provider.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Delete Confirmation Dialog */}
      {deleteConfirmId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-red-100 rounded-full">
                <Trash2 className="h-5 w-5 text-red-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">Delete Run</h3>
            </div>
            <p className="text-sm text-gray-600 mb-6">
              This will permanently delete this optimization run and all its candidates. This action cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteConfirmId(null)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 rounded-lg hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteRunMutation.mutate(deleteConfirmId)}
                disabled={deleteRunMutation.isPending}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {deleteRunMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* New Run Dialog */}
      {showNewRunDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">New Optimization Run</h3>
              <button
                onClick={() => setShowNewRunDialog(false)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Agent</label>
                <select
                  value={newRunAgentId}
                  onChange={e => setNewRunAgentId(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
                >
                  <option value="">Select an agent</option>
                  {agents
                    .filter(a => a.description)
                    .map(a => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Evaluator <span className="text-gray-400">(optional)</span>
                </label>
                <select
                  value={newRunEvaluatorId}
                  onChange={e => setNewRunEvaluatorId(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
                >
                  <option value="">None</option>
                  {evaluators.map(ev => (
                    <option key={ev.id} value={ev.id}>
                      {ev.name || ev.evaluator_id}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                onClick={() => setShowNewRunDialog(false)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={() =>
                  createRunMutation.mutate({
                    agent_id: newRunAgentId,
                    evaluator_id: newRunEvaluatorId || undefined,
                  })
                }
                disabled={!newRunAgentId || createRunMutation.isPending}
                className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {createRunMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                Start Optimization
              </button>
            </div>
            {createRunMutation.isError && (
              <p className="mt-3 text-sm text-red-600">
                {(createRunMutation.error as any)?.response?.data?.detail || 'Failed to create run'}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
