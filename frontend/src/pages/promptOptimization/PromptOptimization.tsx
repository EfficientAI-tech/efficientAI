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
  BarChart3,
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Runs List */}
        <div className="lg:col-span-1 space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Optimization Runs
          </h2>
          {runsLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
            </div>
          ) : runs.length === 0 ? (
            <div className="bg-white rounded-xl border border-gray-200 p-6 text-center">
              <Sparkles className="h-8 w-8 text-gray-300 mx-auto mb-2" />
              <p className="text-sm text-gray-500">No optimization runs yet</p>
              <p className="text-xs text-gray-400 mt-1">
                Start a run to optimize your voice agent's prompt
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {runs.map(run => {
                const status = STATUS_CONFIG[run.status] || STATUS_CONFIG.pending
                const StatusIcon = status.icon
                const isSelected = selectedRunId === run.id
                return (
                  <div
                    key={run.id}
                    className={`relative group w-full text-left p-4 rounded-xl border transition-all cursor-pointer ${
                      isSelected
                        ? 'border-purple-300 bg-purple-50 ring-1 ring-purple-200'
                        : 'border-gray-200 bg-white hover:border-gray-300'
                    }`}
                    onClick={() => {
                      setSelectedRunId(run.id)
                      setCompareCandidateId(null)
                    }}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-sm text-gray-900 truncate">
                        {getAgentName(run.agent_id)}
                      </span>
                      <div className="flex items-center gap-1.5">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${status.color}`}>
                          <StatusIcon className={`h-3 w-3 ${run.status === 'running' ? 'animate-spin' : ''}`} />
                          {status.label}
                        </span>
                        <button
                          onClick={e => {
                            e.stopPropagation()
                            setDeleteConfirmId(run.id)
                          }}
                          className="p-1 text-gray-300 hover:text-red-500 rounded-md hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-all"
                          title="Delete run"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center justify-between text-xs text-gray-500">
                      <span>{format(new Date(run.created_at), 'MMM d, HH:mm')}</span>
                      {run.best_score != null && (
                        <span className="text-green-600 font-medium">
                          Score: {(run.best_score * 100).toFixed(1)}%
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Run Detail & Candidates */}
        <div className="lg:col-span-2">
          {selectedRun ? (
            <div className="space-y-4">
              {/* Run Info */}
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-gray-900">
                    {getAgentName(selectedRun.agent_id)}
                  </h3>
                  <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${STATUS_CONFIG[selectedRun.status]?.color || ''}`}>
                    {STATUS_CONFIG[selectedRun.status]?.label || selectedRun.status}
                  </span>
                </div>
                {selectedRun.error_message && (
                  <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                    {selectedRun.error_message}
                  </div>
                )}
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <span className="text-gray-500">Best Score</span>
                    <p className="font-semibold text-lg text-gray-900">
                      {selectedRun.best_score != null
                        ? `${(selectedRun.best_score * 100).toFixed(1)}%`
                        : '--'}
                    </p>
                  </div>
                  <div>
                    <span className="text-gray-500">Metric Calls</span>
                    <p className="font-semibold text-lg text-gray-900">
                      {selectedRun.num_metric_calls ?? '--'}
                    </p>
                  </div>
                  <div>
                    <span className="text-gray-500">Created</span>
                    <p className="font-semibold text-gray-900">
                      {format(new Date(selectedRun.created_at), 'MMM d, yyyy HH:mm')}
                    </p>
                  </div>
                </div>

                {/* Score Progression */}
                {selectedRun.metric_history && selectedRun.metric_history.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-gray-100">
                    <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2 flex items-center gap-1">
                      <BarChart3 className="h-3.5 w-3.5" />
                      Score Progression
                    </h4>
                    <div className="flex items-end gap-1 h-16">
                      {selectedRun.metric_history.map((entry, i) => (
                        <div
                          key={i}
                          className="flex-1 bg-purple-200 rounded-t transition-all hover:bg-purple-400"
                          style={{ height: `${Math.max(entry.score * 100, 4)}%` }}
                          title={`Iteration ${i + 1}: ${(entry.score * 100).toFixed(1)}%`}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Side-by-Side Comparison */}
              {compareCandidateId && compareCandidate ? (
                <div className="bg-white rounded-xl border border-gray-200 p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h4 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                      <Columns2 className="h-4 w-4 text-purple-500" />
                      Seed vs Optimized Comparison
                    </h4>
                    <button
                      onClick={() => setCompareCandidateId(null)}
                      className="p-1 text-gray-400 hover:text-gray-600 rounded-md hover:bg-gray-100"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-2 flex items-center gap-1">
                        <span className="inline-block w-2 h-2 rounded-full bg-gray-400" />
                        Seed Prompt (Original)
                      </div>
                      <div className={`bg-gray-50 border border-gray-200 rounded-lg p-4 max-h-[400px] overflow-y-auto ${PROSE_CLASSES}`}>
                        <ReactMarkdown>{selectedRun.seed_prompt}</ReactMarkdown>
                      </div>
                    </div>
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-2 flex items-center gap-1">
                        <span className="inline-block w-2 h-2 rounded-full bg-purple-500" />
                        Optimized Candidate
                        {compareCandidate.score != null && (
                          <span className="ml-1 text-purple-600 font-medium">
                            ({(compareCandidate.score * 100).toFixed(1)}%)
                          </span>
                        )}
                      </div>
                      <div className={`bg-purple-50 border border-purple-200 rounded-lg p-4 max-h-[400px] overflow-y-auto ${PROSE_CLASSES}`}>
                        <ReactMarkdown>{compareCandidate.prompt_text}</ReactMarkdown>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                /* Seed Prompt (standalone) */
                <div className="bg-white rounded-xl border border-gray-200 p-5">
                  <h4 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
                    <FileText className="h-4 w-4 text-gray-400" />
                    Seed Prompt (Original)
                  </h4>
                  <div className={`bg-gray-50 border border-gray-200 rounded-lg p-4 max-h-48 overflow-y-auto ${PROSE_CLASSES}`}>
                    <ReactMarkdown>{selectedRun.seed_prompt}</ReactMarkdown>
                  </div>
                </div>
              )}

              {/* Candidates */}
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h4 className="text-sm font-semibold text-gray-700 mb-3">
                  Optimized Candidates ({candidates.length})
                </h4>
                {candidates.length === 0 ? (
                  <p className="text-sm text-gray-400 text-center py-4">
                    {selectedRun.status === 'running'
                      ? 'Optimization in progress...'
                      : 'No candidates generated'}
                  </p>
                ) : (
                  <div className="space-y-3">
                    {candidates.map((candidate, idx) => (
                      <div
                        key={candidate.id}
                        className={`border rounded-lg p-4 ${
                          candidate.is_accepted
                            ? 'border-green-300 bg-green-50'
                            : compareCandidateId === candidate.id
                              ? 'border-purple-300 bg-purple-50/30'
                              : 'border-gray-200'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
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
                          <div className={`mt-3 bg-gray-50 rounded-lg p-4 max-h-48 overflow-y-auto border border-gray-200 ${PROSE_CLASSES}`}>
                            <ReactMarkdown>{candidate.prompt_text}</ReactMarkdown>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
              <Sparkles className="h-10 w-10 text-gray-300 mx-auto mb-3" />
              <p className="text-gray-500">Select a run to view details and candidates</p>
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
