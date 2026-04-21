import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import ReactMarkdown from 'react-markdown'

function stripCodeFences(text: string): string {
  const trimmed = text.trim()
  // Complete fence (opening + closing)
  const full = trimmed.match(/^```[\w]*\n?([\s\S]*?)```\s*$/)
  if (full) return full[1].trim()
  // Opening fence only (no closing — truncated or provider quirk)
  const open = trimmed.match(/^```[\w]*\n?([\s\S]*)$/)
  if (open) return open[1].trim()
  return trimmed
}
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
  X,
  Trash2,
  Columns2,
  FileText,
  RefreshCw,
  Globe,
} from 'lucide-react'
import { format } from 'date-fns'
import { useWalkthroughSectionState } from '../../context/WalkthroughContext'

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
  provider_prompt: string | null
  provider_prompt_synced_at: string | null
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
  const [newRunMaxMetricCalls, setNewRunMaxMetricCalls] = useState(20)
  const [newRunMinibatchSize, setNewRunMinibatchSize] = useState(5)
  const [compareCandidateId, setCompareCandidateId] = useState<string | null>(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)

  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  const { data: integrations = [] } = useQuery<{ id: string; platform: string }[]>({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
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

  useWalkthroughSectionState(
    'prompt-optimization',
    {
      hasSelectedRun: Boolean(selectedRunId),
      hasCompareCandidate: Boolean(compareCandidateId),
      showNewRunDialog,
    },
    [selectedRunId, compareCandidateId, showNewRunDialog]
  )

  const createRunMutation = useMutation({
    mutationFn: (data: { agent_id: string; evaluator_id?: string; config?: Record<string, any> }) =>
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

  const syncPromptMutation = useMutation({
    mutationFn: (agentId: string) => apiClient.syncProviderPrompt(agentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      queryClient.invalidateQueries({ queryKey: ['optimization-runs'] })
    },
  })

  const getAgentName = (agentId: string) =>
    agents.find(a => a.id === agentId)?.name || 'Unknown Agent'

  const getSelectedAgent = () =>
    selectedRun ? agents.find(a => a.id === selectedRun.agent_id) : null

  const PLATFORM_LABELS: Record<string, string> = { vapi: 'Vapi', retell: 'Retell', elevenlabs: 'ElevenLabs' }
  const getProviderLabel = (agent: Agent | null | undefined) => {
    if (!agent?.voice_ai_integration_id) return 'Provider'
    const integration = integrations.find(i => i.id === agent.voice_ai_integration_id)
    if (integration?.platform) return PLATFORM_LABELS[integration.platform] || integration.platform
    return 'Provider'
  }

  return (
    <div className="h-[calc(100vh-7rem)] flex flex-col">
      {/* Main layout — left sidebar + content */}
      <div className="flex-1 flex gap-3 min-h-0">

        {/* Left sidebar — runs list (scrollable) */}
        <div className="w-56 flex-shrink-0 flex flex-col bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-3 py-2.5 border-b border-gray-200 bg-gray-50/50 flex items-center justify-between flex-shrink-0">
            <h2 className="text-xs font-semibold text-gray-700 flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-purple-500" />
              Runs
            </h2>
            <button
              onClick={() => setShowNewRunDialog(true)}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-purple-600 text-white text-[10px] font-medium hover:bg-purple-700 transition-colors"
            >
              <Play className="h-2.5 w-2.5" />
              New
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {runsLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
              </div>
            ) : runs.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 px-3 text-center">
                <Sparkles className="h-8 w-8 text-gray-200 mb-2" />
                <p className="text-xs text-gray-500">No runs yet</p>
                <button
                  onClick={() => setShowNewRunDialog(true)}
                  className="mt-2 text-xs text-purple-600 font-medium hover:text-purple-700"
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
                    onClick={() => { setSelectedRunId(run.id); setCompareCandidateId(null) }}
                    className={`group w-full text-left px-3 py-2.5 border-b border-gray-100 hover:bg-gray-50 transition-colors ${
                      isSelected
                        ? 'bg-purple-50/60 border-l-[3px] border-l-purple-600'
                        : 'border-l-[3px] border-l-transparent'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <StatusIcon className={`h-3 w-3 flex-shrink-0 ${
                          run.status === 'running' ? 'animate-spin text-blue-500' :
                          run.status === 'completed' ? 'text-green-500' :
                          run.status === 'failed' ? 'text-red-500' : 'text-gray-400'
                        }`} />
                        <span className="text-xs font-medium text-gray-900 truncate">{getAgentName(run.agent_id)}</span>
                      </div>
                      <button
                        onClick={e => { e.stopPropagation(); setDeleteConfirmId(run.id) }}
                        className="p-0.5 text-gray-300 hover:text-red-500 rounded opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                    <div className="flex items-center gap-1.5 mt-1">
                      {run.best_score != null && (
                        <span className="text-[10px] font-semibold bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full">
                          {(run.best_score * 100).toFixed(0)}%
                        </span>
                      )}
                      <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium ${status.color}`}>
                        {status.label}
                      </span>
                      <span className="text-[10px] text-gray-400 ml-auto">{format(new Date(run.created_at), 'MMM d')}</span>
                    </div>
                  </button>
                )
              })
            )}
          </div>
        </div>

        {/* Right content — full remaining width */}
        <div className="flex-1 flex flex-col bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden min-h-0">
        {selectedRun ? (
          <>
            {/* Run info strip */}
            <div className="flex items-center justify-between px-5 py-2 border-b border-gray-200 bg-gray-50/50 flex-shrink-0">
              <div className="flex items-center gap-3 min-w-0">
                <h3 className="text-sm font-semibold text-gray-900 truncate">
                  {getAgentName(selectedRun.agent_id)}
                </h3>
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium flex-shrink-0 ${STATUS_CONFIG[selectedRun.status]?.color || ''}`}>
                  {STATUS_CONFIG[selectedRun.status]?.label || selectedRun.status}
                </span>
              </div>
              <div className="flex items-center gap-5 text-xs flex-shrink-0">
                <div>
                  <span className="text-gray-400">Best </span>
                  <span className="font-semibold text-gray-900">
                    {selectedRun.best_score != null ? `${(selectedRun.best_score * 100).toFixed(1)}%` : '--'}
                  </span>
                </div>
                <div>
                  <span className="text-gray-400">Calls </span>
                  <span className="font-semibold text-gray-900">
                    {selectedRun.num_metric_calls ?? '--'}
                    {selectedRun.config?.max_metric_calls && (
                      <span className="text-gray-400 font-normal">/{selectedRun.config.max_metric_calls}</span>
                    )}
                  </span>
                </div>
                {selectedRun.config?.minibatch_size && (
                  <div>
                    <span className="text-gray-400">Batch </span>
                    <span className="font-semibold text-gray-900">{selectedRun.config.minibatch_size}</span>
                  </div>
                )}
                <span className="text-gray-400">
                  {format(new Date(selectedRun.created_at), 'MMM d, HH:mm')}
                </span>
                {selectedRun.metric_history && selectedRun.metric_history.length > 0 && (
                  <div className="flex items-end gap-px h-5 pl-3 border-l border-gray-200" title="Score progression">
                    {selectedRun.metric_history.map((entry, i) => (
                      <div
                        key={i}
                        className="w-1 bg-purple-300 rounded-t hover:bg-purple-500 transition-colors"
                        style={{ height: `${Math.max(entry.score * 100, 10)}%` }}
                        title={`Iteration ${i + 1}: ${(entry.score * 100).toFixed(1)}%`}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>

            {selectedRun.error_message && (
              <div className="mx-4 mt-2 p-2.5 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 flex-shrink-0">
                {selectedRun.error_message}
              </div>
            )}

            {/* Content Area — candidates sidebar + prompt panels */}
            <div className="flex-1 flex min-h-0">

              {/* Candidates Sidebar */}
              {candidates.length > 0 && (
                <div className="w-48 flex-shrink-0 border-r border-gray-200 flex flex-col overflow-hidden bg-gray-50/30">
                  <div className="px-3 py-2 border-b border-gray-200 bg-gray-50">
                    <h4 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                      Candidates ({candidates.length})
                    </h4>
                  </div>
                  <div className="flex-1 overflow-y-auto">
                    {candidates.map((candidate, idx) => {
                      const isSelected = compareCandidateId === candidate.id
                      return (
                        <button
                          key={candidate.id}
                          onClick={() => setCompareCandidateId(isSelected ? null : candidate.id)}
                          className={`w-full text-left px-3 py-2 border-b border-gray-100 transition-colors ${
                            isSelected
                              ? 'bg-purple-50 border-l-[3px] border-l-purple-500'
                              : 'hover:bg-gray-50 border-l-[3px] border-l-transparent'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-medium text-gray-900">#{idx + 1}</span>
                            <div className="flex items-center gap-1">
                              {candidate.score != null && (
                                <span className="text-[10px] bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded-full font-semibold">
                                  {(candidate.score * 100).toFixed(1)}%
                                </span>
                              )}
                              {candidate.is_accepted && <Check className="h-3 w-3 text-green-600" />}
                              {candidate.pushed_to_provider_at && <Upload className="h-3 w-3 text-blue-500" />}
                            </div>
                          </div>
                          {isSelected && (
                            <div className="flex items-center gap-1 mt-1.5">
                              {!candidate.is_accepted && (
                                <button
                                  onClick={e => { e.stopPropagation(); acceptMutation.mutate({ runId: selectedRun.id, candidateId: candidate.id }) }}
                                  disabled={acceptMutation.isPending}
                                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-medium text-green-700 bg-green-50 rounded hover:bg-green-100 border border-green-200"
                                >
                                  <Check className="h-2.5 w-2.5" /> Accept
                                </button>
                              )}
                              {candidate.is_accepted && !candidate.pushed_to_provider_at && (
                                <button
                                  onClick={e => { e.stopPropagation(); pushMutation.mutate({ runId: selectedRun.id, candidateId: candidate.id }) }}
                                  disabled={pushMutation.isPending}
                                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 bg-blue-50 rounded hover:bg-blue-100 border border-blue-200"
                                >
                                  {pushMutation.isPending ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <ArrowUpRight className="h-2.5 w-2.5" />}
                                  Push
                                </button>
                              )}
                            </div>
                          )}
                          {candidate.reflection_summary && (
                            <p className="text-[10px] text-gray-400 mt-1 line-clamp-1">{candidate.reflection_summary}</p>
                          )}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Prompt panels */}
              <div className="flex-1 flex min-h-0">
                {/* Seed / Provider Prompt */}
                <div className="flex-1 flex flex-col min-h-0 min-w-0">
                  <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50/50 flex-shrink-0">
                    <div className="flex items-center gap-2 text-xs font-medium text-gray-600">
                      <span className="inline-block w-1.5 h-1.5 rounded-full bg-gray-400" />
                      {(() => {
                        const agent = getSelectedAgent()
                        if (agent?.provider_prompt) {
                          return (
                            <>
                              <Globe className="h-3.5 w-3.5 text-blue-500" />
                              {getProviderLabel(agent)} Prompt
                              {agent.provider_prompt_synced_at && (
                                <span className="text-gray-400 font-normal">
                                  &middot; {format(new Date(agent.provider_prompt_synced_at), 'MMM d, HH:mm')}
                                </span>
                              )}
                            </>
                          )
                        }
                        return (
                          <>
                            <FileText className="h-3.5 w-3.5 text-gray-400" />
                            EfficientAI Test Agent Prompt
                          </>
                        )
                      })()}
                    </div>
                    {(() => {
                      const agent = getSelectedAgent()
                      if (agent?.voice_ai_integration_id && agent?.voice_ai_agent_id) {
                        return (
                          <button
                            onClick={() => syncPromptMutation.mutate(agent.id)}
                            disabled={syncPromptMutation.isPending}
                            className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium text-blue-700 bg-blue-50 rounded hover:bg-blue-100 border border-blue-200 transition-colors disabled:opacity-50"
                          >
                            <RefreshCw className={`h-2.5 w-2.5 ${syncPromptMutation.isPending ? 'animate-spin' : ''}`} />
                            {syncPromptMutation.isPending ? 'Syncing...' : 'Sync'}
                          </button>
                        )
                      }
                      return null
                    })()}
                  </div>
                  <div className={`flex-1 overflow-y-auto p-4 ${PROSE_CLASSES}`}>
                    <ReactMarkdown>{stripCodeFences(
                      getSelectedAgent()?.provider_prompt || selectedRun.seed_prompt
                    )}</ReactMarkdown>
                  </div>
                </div>

                {/* Selected Candidate Prompt */}
                {compareCandidateId && compareCandidate ? (
                  <div className="flex-1 flex flex-col min-h-0 min-w-0 border-l border-gray-200">
                    <div className="flex items-center justify-between px-4 py-2 border-b border-purple-200 bg-purple-50/50 flex-shrink-0">
                      <div className="flex items-center gap-2 text-xs font-medium text-purple-700">
                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-purple-500" />
                        Optimized Candidate
                        {compareCandidate.score != null && (
                          <span className="bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded-full text-[10px]">
                            {(compareCandidate.score * 100).toFixed(1)}%
                          </span>
                        )}
                        {compareCandidate.is_accepted && (
                          <span className="bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full flex items-center gap-0.5 text-[10px]">
                            <Check className="h-2.5 w-2.5" /> Accepted
                          </span>
                        )}
                      </div>
                      <button
                        onClick={() => setCompareCandidateId(null)}
                        className="p-0.5 text-gray-400 hover:text-gray-600 rounded hover:bg-gray-100"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <div className={`flex-1 overflow-y-auto p-4 ${PROSE_CLASSES}`}>
                      <ReactMarkdown>{stripCodeFences(compareCandidate.prompt_text)}</ReactMarkdown>
                    </div>
                  </div>
                ) : (
                  <div className="flex-1 flex flex-col items-center justify-center border-l border-gray-200 bg-gray-50/30 text-center px-6">
                    {candidates.length > 0 ? (
                      <>
                        <Columns2 className="h-8 w-8 text-gray-200 mb-2" />
                        <p className="text-xs text-gray-500">Select a candidate to compare</p>
                      </>
                    ) : selectedRun.status === 'running' ? (
                      <>
                        <Loader2 className="h-8 w-8 text-purple-300 mb-2 animate-spin" />
                        <p className="text-xs text-gray-500">Optimization in progress...</p>
                      </>
                    ) : selectedRun.status === 'pending' ? (
                      <>
                        <Clock className="h-8 w-8 text-gray-200 mb-2" />
                        <p className="text-xs text-gray-500">Waiting to start...</p>
                      </>
                    ) : (
                      <>
                        <Sparkles className="h-8 w-8 text-gray-200 mb-2" />
                        <p className="text-xs text-gray-500">No candidates generated</p>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
            <Sparkles className="h-12 w-12 text-gray-200 mb-3" />
            <h3 className="text-sm font-medium text-gray-900 mb-1">Select an optimization run</h3>
            <p className="text-xs text-gray-500 max-w-xs">
              Choose a run from the list to view candidates, compare prompts, and push results.
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
                    .filter(a => a.description || a.provider_prompt)
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

              <div className="border-t border-gray-200 pt-4">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">Optimization Settings</p>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Max Metric Calls
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={500}
                      value={newRunMaxMetricCalls}
                      onChange={e => setNewRunMaxMetricCalls(Math.max(1, parseInt(e.target.value) || 1))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
                    />
                    <p className="mt-1 text-xs text-gray-400">Total evaluation budget</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Minibatch Size
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={newRunMinibatchSize}
                      onChange={e => setNewRunMinibatchSize(Math.max(1, parseInt(e.target.value) || 1))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
                    />
                    <p className="mt-1 text-xs text-gray-400">Examples per iteration</p>
                  </div>
                </div>
                <p className="mt-2 text-xs text-gray-400">
                  ~{Math.max(1, Math.floor(newRunMaxMetricCalls / newRunMinibatchSize))} iterations
                  {' / ~'}{newRunMaxMetricCalls + Math.max(1, Math.floor(newRunMaxMetricCalls / newRunMinibatchSize))} LLM calls
                </p>
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
                    config: {
                      max_metric_calls: newRunMaxMetricCalls,
                      minibatch_size: newRunMinibatchSize,
                    },
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
