import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { useAgentStore } from '../../../store/agentStore'
import { ModelProvider } from '../../../types/api'
import Button from '../../../components/Button'
import { ChevronLeft, ChevronRight, Info, X, Check } from 'lucide-react'
import EvaluatorMetricPicker from './EvaluatorMetricPicker'
import EvaluatorLlmPicker from './EvaluatorLlmPicker'
import { MODERN_INPUT_CLASS, MODERN_SELECT_CLASS } from './evaluatorUi'
import { normalizeSelectedMetricIds, type MetricRow } from './metricSelectionUtils'

const DEFAULT_SCENARIO_NAMES = [
  'Cancel Subscription',
  'Check Balance',
  'Technical Support',
  'Make Complaint',
  'Product Inquiry',
]

const STEPS = ['Agent & Persona', 'Scenarios', 'Metrics', 'Review']

interface Props {
  open: boolean
  onClose: () => void
  isSubmitting: boolean
  onSubmit: (payload: {
    name?: string
    agent_id: string
    persona_id: string
    scenario_ids: string[]
    metric_ids?: string[]
    llm_provider?: string
    llm_model?: string
    tags?: string[]
    default_runs_per_combination?: number
  }) => void
}

export default function EvaluatorSuiteWizard({ open, onClose, isSubmitting, onSubmit }: Props) {
  const { selectedAgent } = useAgentStore()
  const [step, setStep] = useState(0)
  const [modalAgentId, setModalAgentId] = useState('')
  const [selectedPersonaId, setSelectedPersonaId] = useState('')
  const [selectedScenarioIds, setSelectedScenarioIds] = useState<string[]>([])
  const [selectedMetricIds, setSelectedMetricIds] = useState<string[]>([])
  const [llmProvider, setLlmProvider] = useState<ModelProvider | null>(null)
  const [llmModel, setLlmModel] = useState('')
  const [suiteName, setSuiteName] = useState('')
  const [defaultRuns, setDefaultRuns] = useState(1)

  useEffect(() => {
    if (open) {
      setStep(0)
      setModalAgentId(selectedAgent?.id || '')
      setSelectedPersonaId('')
      setSelectedScenarioIds([])
      setSelectedMetricIds([])
      setLlmProvider(null)
      setLlmModel('')
      setSuiteName('')
      setDefaultRuns(1)
    }
  }, [open, selectedAgent?.id])

  const { data: agents = [] } = useQuery({ queryKey: ['agents'], queryFn: () => apiClient.listAgents(), enabled: open })
  const { data: personas = [] } = useQuery({ queryKey: ['personas'], queryFn: () => apiClient.listPersonas(), enabled: open })
  const { data: scenarios = [] } = useQuery({
    queryKey: ['scenarios', modalAgentId],
    queryFn: () => apiClient.listScenarios(0, 100, modalAgentId),
    enabled: open && !!modalAgentId,
  })
  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics', 'agent'],
    queryFn: () => apiClient.listMetrics('agent', true),
    enabled: open,
  })
  const selectedAgentObj = agents.find((a: any) => a.id === modalAgentId)
  const { data: agentVoiceBundle } = useQuery({
    queryKey: ['voicebundle', selectedAgentObj?.voice_bundle_id],
    queryFn: () => apiClient.getVoiceBundle(selectedAgentObj!.voice_bundle_id),
    enabled: open && !!selectedAgentObj?.voice_bundle_id,
  })

  const voiceBundleTtsProvider = agentVoiceBundle?.tts_provider
    ? String(agentVoiceBundle.tts_provider).toLowerCase()
    : null

  const filteredPersonas = voiceBundleTtsProvider
    ? personas.filter((p: any) => p.tts_provider?.toLowerCase() === voiceBundleTtsProvider)
    : personas

  const filteredScenarios = scenarios.filter((s: any) => !DEFAULT_SCENARIO_NAMES.includes(s.name))

  const isInbound = selectedAgentObj?.call_type === 'inbound'
  const isOutboundPhone =
    selectedAgentObj?.call_medium === 'phone_call' && selectedAgentObj?.call_type !== 'inbound'
  const totalRuns = selectedScenarioIds.length * defaultRuns

  const toggleScenario = (id: string) => {
    setSelectedScenarioIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const canNext = () => {
    if (step === 0) return !!modalAgentId && !!selectedPersonaId
    if (step === 1) return selectedScenarioIds.length > 0
    return true
  }

  const handleSubmit = () => {
    const metricRows = metrics as MetricRow[]
    const normalizedMetrics = selectedMetricIds.length > 0
      ? normalizeSelectedMetricIds(selectedMetricIds, metricRows)
      : []
    onSubmit({
      name: suiteName.trim() || undefined,
      agent_id: modalAgentId,
      persona_id: selectedPersonaId,
      scenario_ids: selectedScenarioIds,
      metric_ids: normalizedMetrics.length > 0 ? normalizedMetrics : undefined,
      llm_provider: llmProvider || undefined,
      llm_model: llmProvider && llmModel ? llmModel : undefined,
      default_runs_per_combination: defaultRuns,
    })
  }

  if (!open) return null

  const modal = (
    <div className="fixed inset-0 z-[9999] overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose} />
        <div className="relative bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Create Evaluator Suite</h2>
              <p className="text-sm text-gray-500 mt-0.5">Step {step + 1} of {STEPS.length}: {STEPS[step]}</p>
            </div>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-100">
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="px-6 py-4 border-b border-gray-100 bg-gray-50/50">
            <div className="flex gap-1">
              {STEPS.map((label, i) => (
                <div
                  key={label}
                  className={`flex-1 flex items-center justify-center gap-1.5 text-xs py-2 px-2 rounded-lg transition-colors ${
                    i === step
                      ? 'bg-primary-50 text-primary-800 font-semibold border border-primary-200'
                      : i < step
                        ? 'text-gray-700 bg-white border border-gray-200'
                        : 'text-gray-400'
                  }`}
                >
                  {i < step && <Check className="h-3 w-3 text-emerald-600" />}
                  <span className="hidden sm:inline truncate">{label}</span>
                  <span className="sm:hidden">{i + 1}</span>
                </div>
              ))}
            </div>
          </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {step === 0 && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Agent *</label>
                <select
                  value={modalAgentId}
                  onChange={(e) => {
                    setModalAgentId(e.target.value)
                    setSelectedPersonaId('')
                    setSelectedScenarioIds([])
                  }}
                  className={MODERN_SELECT_CLASS}
                >
                  <option value="">Select an agent</option>
                  {agents.map((a: any) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Persona *</label>
                {voiceBundleTtsProvider && (
                  <div className="mb-2 flex items-start gap-2 p-2 bg-blue-50 border border-blue-200 rounded text-xs text-blue-700">
                    <Info className="h-4 w-4 shrink-0 mt-0.5" />
                    Showing personas matching TTS provider {voiceBundleTtsProvider}
                  </div>
                )}
                <div className="space-y-2 max-h-48 overflow-y-auto border border-gray-200 rounded-xl p-3 bg-gray-50/30">
                  {filteredPersonas.map((p: any) => (
                    <label key={p.id} className={`flex items-start gap-3 cursor-pointer p-2.5 rounded-lg border transition-colors ${
                      selectedPersonaId === p.id ? 'bg-primary-50 border-primary-200' : 'border-transparent hover:bg-white hover:border-gray-200'
                    }`}>
                      <input
                        type="radio"
                        name="persona"
                        checked={selectedPersonaId === p.id}
                        onChange={() => setSelectedPersonaId(p.id)}
                        className="mt-1"
                      />
                      <div className="min-w-0">
                        <span className="text-sm font-medium">{p.name}</span>
                        {p.description?.trim() ? (
                          <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{p.description}</p>
                        ) : null}
                      </div>
                    </label>
                  ))}
                  {filteredPersonas.length === 0 && (
                    <p className="text-sm text-gray-500 p-2">No compatible personas. Select an agent first.</p>
                  )}
                </div>
              </div>
            </>
          )}

          {step === 1 && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Scenarios * ({selectedScenarioIds.length} selected)
              </label>
              <div className="space-y-2 max-h-64 overflow-y-auto border border-gray-200 rounded-xl p-3 bg-gray-50/30">
                {filteredScenarios.map((s: any) => (
                  <label key={s.id} className={`flex items-center gap-3 cursor-pointer p-2.5 rounded-lg border transition-colors ${
                    selectedScenarioIds.includes(s.id) ? 'bg-primary-50 border-primary-200' : 'border-transparent hover:bg-white hover:border-gray-200'
                  }`}>
                    <input
                      type="checkbox"
                      checked={selectedScenarioIds.includes(s.id)}
                      onChange={() => toggleScenario(s.id)}
                    />
                    <span className="text-sm">{s.name}</span>
                  </label>
                ))}
                {modalAgentId && filteredScenarios.length === 0 && (
                  <p className="text-sm text-gray-500 p-2">
                    No scenarios linked to this agent. Link scenarios to the agent on the Scenarios page, then return here.
                  </p>
                )}
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-6">
              <EvaluatorMetricPicker
                selectedMetricIds={selectedMetricIds}
                onChange={setSelectedMetricIds}
              />
              <EvaluatorLlmPicker
                llmProvider={llmProvider}
                llmModel={llmModel}
                onProviderChange={setLlmProvider}
                onModelChange={setLlmModel}
              />
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <div className="p-5 bg-gray-50 rounded-xl border border-gray-100 text-sm space-y-3">
                <p><span className="font-medium">Agent:</span> {selectedAgentObj?.name || '—'}</p>
                <p><span className="font-medium">Persona:</span> {personas.find((p: any) => p.id === selectedPersonaId)?.name || '—'}</p>
                {personas.find((p: any) => p.id === selectedPersonaId)?.description?.trim() ? (
                  <p className="text-gray-600 text-xs pl-4 border-l-2 border-gray-200">
                    {personas.find((p: any) => p.id === selectedPersonaId)?.description}
                  </p>
                ) : null}
                <p><span className="font-medium">Scenarios:</span> {selectedScenarioIds.length} combination{selectedScenarioIds.length !== 1 ? 's' : ''}</p>
                <ul className="list-disc list-inside text-gray-600 ml-2">
                  {selectedScenarioIds.map((id) => (
                    <li key={id}>{filteredScenarios.find((s: any) => s.id === id)?.name || id}</li>
                  ))}
                </ul>
                <p><span className="font-medium">Metrics:</span> {selectedMetricIds.length > 0 ? selectedMetricIds.length : 'All agent metrics'}</p>
                <p>
                  <span className="font-medium">Evaluation LLM:</span>{' '}
                  {llmProvider ? `${llmProvider}${llmModel ? ` · ${llmModel}` : ''}` : 'Default (OpenAI gpt-4o)'}
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Suite name</label>
                <input
                  type="text"
                  value={suiteName}
                  onChange={(e) => setSuiteName(e.target.value)}
                  placeholder="Optional display name"
                  className={MODERN_INPUT_CLASS}
                />
              </div>
              {isOutboundPhone || selectedAgentObj?.call_medium === 'web_call' ? (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Default runs per combination</label>
                  <input
                    type="number"
                    min={1}
                    value={defaultRuns}
                    onChange={(e) => setDefaultRuns(Math.max(1, parseInt(e.target.value, 10) || 1))}
                    className={`${MODERN_INPUT_CLASS} w-28`}
                  />
                  <div className="mt-3 rounded-lg bg-indigo-50 border border-indigo-100 px-4 py-3 text-sm text-indigo-800">
                    Total batch runs: <strong>{selectedScenarioIds.length} × {defaultRuns} = {totalRuns}</strong>
                  </div>
                </div>
              ) : isInbound ? (
                <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl p-4">
                  Inbound agent — scenarios rotate automatically when callers reach the agent. No manual test calls are placed.
                </p>
              ) : null}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200 bg-gray-50 rounded-b-lg">
          <Button
            variant="outline"
            onClick={() => (step === 0 ? onClose() : setStep(step - 1))}
            leftIcon={<ChevronLeft className="h-4 w-4" />}
          >
            {step === 0 ? 'Cancel' : 'Back'}
          </Button>
          {step < STEPS.length - 1 ? (
            <Button
              variant="primary"
              onClick={() => setStep(step + 1)}
              disabled={!canNext()}
              rightIcon={<ChevronRight className="h-4 w-4" />}
            >
              Next
            </Button>
          ) : (
            <Button variant="primary" onClick={handleSubmit} isLoading={isSubmitting} disabled={isSubmitting}>
              Create Suite
            </Button>
          )}
        </div>
        </div>
      </div>
    </div>
  )

  if (typeof document === 'undefined') return null
  return createPortal(modal, document.body)
}
