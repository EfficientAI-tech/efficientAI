import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { apiClient, EvaluatorSuite, EvaluatorSuiteCombination } from '../../../lib/api'
import Button from '../../../components/Button'
import ConfirmModal from '../../../components/ConfirmModal'
import {
  Eye,
  Plus,
  Trash2,
  Loader2,
  Layers,
  Brain,
  BarChart3,
  User,
  Bot,
  FileText,
} from 'lucide-react'
import { useToast } from '../../../hooks/useToast'
import { ModelProvider } from '../../../types/api'
import EvaluatorOutboundCallPanel from '../components/EvaluatorOutboundCallPanel'
import EvaluatorInboundCallPanel from '../components/EvaluatorInboundCallPanel'
import EvaluatorSmartRunModal from '../components/EvaluatorSmartRunModal'
import EvaluatorMetricPicker from '../components/EvaluatorMetricPicker'
import EvaluatorLlmPicker from '../components/EvaluatorLlmPicker'
import ScenarioViewModal from '../components/ScenarioViewModal'
import EvaluatorDetailHeader from '../components/EvaluatorDetailHeader'
import EvaluatorMetricsDisplay from '../components/EvaluatorMetricsDisplay'
import { MODERN_INPUT_CLASS, MODERN_SELECT_CLASS, StatCard } from '../components/evaluatorUi'
import { normalizeSelectedMetricIds, type MetricRow } from '../components/metricSelectionUtils'

const DEFAULT_SCENARIO_NAMES = [
  'Cancel Subscription',
  'Check Balance',
  'Technical Support',
  'Make Complaint',
  'Product Inquiry',
]

export default function EvaluatorDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()

  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editMetricIds, setEditMetricIds] = useState<string[]>([])
  const [editLlmProvider, setEditLlmProvider] = useState<ModelProvider | null>(null)
  const [editLlmModel, setEditLlmModel] = useState('')
  const [scenarioToAdd, setScenarioToAdd] = useState('')
  const [viewCombination, setViewCombination] = useState<EvaluatorSuiteCombination | null>(null)
  const [showRunModal, setShowRunModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)

  const { data: suite, isLoading, error } = useQuery<EvaluatorSuite>({
    queryKey: ['evaluator-suite', id],
    queryFn: () => apiClient.getEvaluatorSuite(id!),
    enabled: !!id,
    retry: false,
  })

  const { data: agent } = useQuery({
    queryKey: ['agent', suite?.agent_id],
    queryFn: () => apiClient.getAgent(suite!.agent_id),
    enabled: !!suite?.agent_id,
  })

  const { data: scenarios = [] } = useQuery({
    queryKey: ['scenarios'],
    queryFn: () => apiClient.listScenarios(),
    enabled: isEditing,
  })

  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics', 'agent'],
    queryFn: () => apiClient.listMetrics('agent', true),
    enabled: !!suite,
  })

  useEffect(() => {
    if (suite && !isEditing) {
      setEditName(suite.name || '')
      const rows = metrics as MetricRow[]
      setEditMetricIds(
        suite.metric_ids?.length
          ? normalizeSelectedMetricIds(suite.metric_ids, rows)
          : [],
      )
      setEditLlmProvider((suite.llm_provider as ModelProvider) || null)
      setEditLlmModel(suite.llm_model || '')
    }
  }, [suite, isEditing, metrics])

  const invalidateSuite = () => {
    queryClient.invalidateQueries({ queryKey: ['evaluator-suite', id] })
    queryClient.invalidateQueries({ queryKey: ['evaluator-suites'] })
  }

  const updateMutation = useMutation({
    mutationFn: (data: Parameters<typeof apiClient.updateEvaluatorSuite>[1]) =>
      apiClient.updateEvaluatorSuite(id!, data),
    onSuccess: () => {
      invalidateSuite()
      setIsEditing(false)
      showToast('Suite updated', 'success')
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || 'Failed to update suite', 'error')
    },
  })

  const addScenariosMutation = useMutation({
    mutationFn: (scenarioIds: string[]) => apiClient.addEvaluatorSuiteScenarios(id!, scenarioIds),
    onSuccess: () => {
      invalidateSuite()
      setScenarioToAdd('')
      showToast('Scenario added', 'success')
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || 'Failed to add scenario', 'error')
    },
  })

  const removeScenarioMutation = useMutation({
    mutationFn: (scenarioId: string) => apiClient.removeEvaluatorSuiteScenario(id!, scenarioId),
    onSuccess: () => {
      invalidateSuite()
      showToast('Scenario removed', 'success')
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || 'Failed to remove scenario', 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => apiClient.deleteEvaluatorSuite(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluator-suites'] })
      navigate('/evaluate-test-agents')
      showToast('Suite deleted', 'success')
    },
  })

  const handleSave = () => {
    const rows = metrics as MetricRow[]
    const normalized = editMetricIds.length > 0
      ? normalizeSelectedMetricIds(editMetricIds, rows)
      : []
    updateMutation.mutate({
      name: editName.trim() || undefined,
      metric_ids: normalized.length > 0 ? normalized : null,
      llm_provider: editLlmProvider,
      llm_model: editLlmProvider ? editLlmModel : null,
    })
  }

  const handleStartEdit = () => {
    if (!suite) return
    setEditName(suite.name || '')
    const rows = metrics as MetricRow[]
    setEditMetricIds(
      suite.metric_ids?.length
        ? normalizeSelectedMetricIds(suite.metric_ids, rows)
        : [],
    )
    setEditLlmProvider((suite.llm_provider as ModelProvider) || null)
    setEditLlmModel(suite.llm_model || '')
    setIsEditing(true)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        <Loader2 className="w-6 h-6 animate-spin mr-2" />
        Loading suite…
      </div>
    )
  }

  if (error || !suite) {
    return (
      <div className="space-y-6">
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <FileText className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">Evaluator suite not found</h3>
          <p className="text-gray-500 mb-6">This suite may have been deleted or you may not have access.</p>
          <Button variant="outline" onClick={() => navigate('/evaluate-test-agents')}>
            Back to evaluators
          </Button>
        </div>
      </div>
    )
  }

  const isInbound = suite.agent_call_type === 'inbound'
  const firstCombo = suite.combinations[0]
  const existingScenarioIds = new Set(suite.combinations.map((c) => c.scenario_id))
  const availableScenarios = (scenarios as any[]).filter(
    (s) => !DEFAULT_SCENARIO_NAMES.includes(s.name) && !existingScenarioIds.has(s.id),
  )

  const llmLabel = suite.llm_provider
    ? `${suite.llm_provider}${suite.llm_model ? ` · ${suite.llm_model}` : ''}`
    : 'Default (OpenAI gpt-4o)'

  const metricRows = metrics as MetricRow[]

  const displayTitle = isEditing
    ? 'Edit Evaluator Suite'
    : suite.name || `${suite.agent_name} · ${suite.persona_name}`

  return (
    <div className="space-y-6">
      <ToastContainer />

      <EvaluatorDetailHeader
        title={displayTitle}
        subtitle={!isEditing ? `${suite.combination_count} scenario combination${suite.combination_count !== 1 ? 's' : ''}` : undefined}
        callMedium={suite.agent_call_medium}
        callType={suite.agent_call_type}
        isEditing={isEditing}
        isInbound={isInbound}
        isSaving={updateMutation.isPending}
        onEdit={handleStartEdit}
        onCancelEdit={() => setIsEditing(false)}
        onSave={handleSave}
        onRun={() => setShowRunModal(true)}
        onDelete={() => setShowDeleteModal(true)}
      />

      {/* Overview card */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Configuration</h2>
        </div>
        <div className="p-6 space-y-6">
          {isEditing && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Suite name</label>
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className={MODERN_INPUT_CLASS}
                placeholder="Optional display name"
              />
            </div>
          )}

          {!isEditing && (
            <motion.div
              className="grid grid-cols-2 md:grid-cols-4 gap-4"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <StatCard
                label="Agent"
                value={suite.agent_name || '—'}
                accentClass="text-base font-semibold text-gray-900"
                iconBgClass="bg-blue-50"
                iconClass="text-blue-600"
                icon={<Bot className="w-5 h-5" />}
              />
              <StatCard
                label="Persona"
                value={suite.persona_name || '—'}
                accentClass="text-base font-semibold text-gray-900"
                iconBgClass="bg-purple-50"
                iconClass="text-purple-600"
                icon={<User className="w-5 h-5" />}
              />
              <StatCard
                label="Scenarios"
                value={suite.combination_count}
                accentClass="text-indigo-600"
                iconBgClass="bg-indigo-50"
                iconClass="text-indigo-500"
                icon={<Layers className="w-5 h-5" />}
              />
              <StatCard
                label="Runs / combo"
                value={suite.default_runs_per_combination}
                accentClass="text-gray-900"
                iconBgClass="bg-slate-100"
                iconClass="text-slate-600"
                icon={<BarChart3 className="w-5 h-5" />}
              />
            </motion.div>
          )}

          {!isEditing && (
            <div className="space-y-4">
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <BarChart3 className="h-4 w-4 text-gray-500" />
                  <h3 className="text-sm font-semibold text-gray-900">Selected metrics</h3>
                </div>
                <EvaluatorMetricsDisplay
                  selectedMetricIds={suite.metric_ids}
                  metrics={metricRows}
                />
              </div>
              <div className="rounded-xl border border-purple-100 bg-purple-50/30 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Brain className="h-4 w-4 text-purple-600" />
                  <h3 className="text-sm font-semibold text-gray-900">Evaluation LLM</h3>
                </div>
                <p className="text-sm text-gray-600">{llmLabel}</p>
              </div>
            </div>
          )}

          {isEditing && (
            <div className="space-y-6 border-t border-gray-100 pt-6">
              <div>
                <h3 className="text-sm font-semibold text-gray-900 mb-3">Metrics</h3>
                <EvaluatorMetricPicker selectedMetricIds={editMetricIds} onChange={setEditMetricIds} />
              </div>
              <EvaluatorLlmPicker
                llmProvider={editLlmProvider}
                llmModel={editLlmModel}
                onProviderChange={setEditLlmProvider}
                onModelChange={setEditLlmModel}
              />
            </div>
          )}
        </div>
      </div>

      {isInbound ? (
        <EvaluatorInboundCallPanel suite={suite} agentPhoneNumber={agent?.phone_number} />
      ) : firstCombo ? (
        <EvaluatorOutboundCallPanel
          evaluatorId={firstCombo.id}
          agentId={suite.agent_id}
          personaId={suite.persona_id}
          scenarioId={firstCombo.scenario_id}
          personaName={suite.persona_name || undefined}
          scenarioName={firstCombo.scenario_name || undefined}
          callMedium={suite.agent_call_medium || 'phone_call'}
          callType={suite.agent_call_type || 'outbound'}
          showToast={showToast}
        />
      ) : null}

      {/* Scenarios table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center gap-3">
            <FileText className="h-5 w-5 text-green-600" />
            <h2 className="text-lg font-semibold text-gray-900">Scenario Combinations</h2>
            <span className="px-2 py-0.5 text-xs font-medium text-green-700 bg-green-100 rounded-full">
              {suite.combination_count}
            </span>
          </div>
          {isEditing && availableScenarios.length > 0 && (
            <div className="flex items-center gap-2">
              <select
                value={scenarioToAdd}
                onChange={(e) => setScenarioToAdd(e.target.value)}
                className={`${MODERN_SELECT_CLASS} sm:w-56`}
              >
                <option value="">Add scenario…</option>
                {availableScenarios.map((s: any) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
              <Button
                size="sm"
                variant="primary"
                onClick={() => scenarioToAdd && addScenariosMutation.mutate([scenarioToAdd])}
                disabled={!scenarioToAdd}
                isLoading={addScenariosMutation.isPending}
                leftIcon={<Plus className="h-3.5 w-3.5" />}
              >
                Add
              </Button>
            </div>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Evaluator ID</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Scenario</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {suite.combinations.map((c) => (
                <tr key={c.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4 font-mono text-xs text-gray-500">{c.evaluator_id}</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-gray-400 shrink-0" />
                      <span className="text-sm font-medium text-gray-900">{c.scenario_name || c.scenario_id}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setViewCombination(c)}
                        leftIcon={<Eye className="h-4 w-4" />}
                        className="text-blue-600 hover:text-blue-700 hover:bg-blue-50"
                      >
                        View
                      </Button>
                      {isEditing && suite.combinations.length > 1 && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => removeScenarioMutation.mutate(c.scenario_id)}
                          isLoading={removeScenarioMutation.isPending}
                          leftIcon={<Trash2 className="h-4 w-4" />}
                          className="text-red-600 hover:text-red-700 hover:bg-red-50"
                        >
                          Remove
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {isEditing && suite.combinations.length <= 1 && (
          <p className="px-6 py-3 text-xs text-gray-500 border-t border-gray-100 bg-gray-50/50">
            At least one scenario is required — you cannot remove the last one.
          </p>
        )}
      </div>

      <ScenarioViewModal combination={viewCombination} onClose={() => setViewCombination(null)} />

      {!isInbound && (
        <EvaluatorSmartRunModal
          open={showRunModal}
          onClose={() => setShowRunModal(false)}
          suites={[suite]}
          showToast={showToast}
        />
      )}

      <ConfirmModal
        isOpen={showDeleteModal}
        title="Delete evaluator suite?"
        description="Historical evaluation results are preserved. This action cannot be undone."
        confirmLabel="Delete"
        onConfirm={() => deleteMutation.mutate()}
        onCancel={() => setShowDeleteModal(false)}
        isLoading={deleteMutation.isPending}
        variant="danger"
      />
    </div>
  )
}
