import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronLeft, ChevronRight, Play, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorDetail } from '../../lib/authSession'
import { isChatMedium } from '../../lib/agentMedium'
import { isFullLlmToLlmChatConnection } from '../../lib/chatConnectionCapabilities'
import { metricListSurfaceForAgentMedium } from '../../lib/metricSurfaces'
import { connectionTypeLabel } from '../agents/components/create/chatAgentFormUtils'
import Button from '../../components/Button'
import SimulationMetricPicker from './SimulationMetricPicker'
import {
  formatMetricScopeLabel,
  isGoldenMetric,
  scenariosWithNoApplicableMetrics,
  syncSimulationMetricSelection,
} from './simulationMetricScope'
import EvaluatorLlmPicker from '../evaluators/components/EvaluatorLlmPicker'
import {
  normalizeSelectedMetricIds,
  type MetricRow,
} from '../evaluators/components/metricSelectionUtils'
import type { MetricSuccessCriterion, ModelProvider, SimulationRun } from '../../types/api'
import MetricSuccessCriteriaStep from './MetricSuccessCriteriaStep'
import {
  criteriaStepValid,
  formatCriterionSummary,
  syncCriteriaWithMetrics,
} from './metricSuccessCriteriaUtils'
import { formatLlmPair } from './simulationFormat'

const STEPS = ['Scenarios & personas', 'Metrics', 'Success criteria', 'Settings & review'] as const

const EMPTY_METRIC_ROWS: MetricRow[] = []

interface ScenarioRow {
  id: string
  name: string
  description?: string | null
}

interface PersonaRow {
  id: string
  name: string
  simulation_medium?: string | null
}

interface Props {
  isOpen: boolean
  onClose: () => void
  agent: {
    id: string
    name: string
    call_medium?: string | null
    chat_connection_type?: string | null
    main_llm_provider?: string | null
    main_llm_model?: string | null
    test_llm_provider?: string | null
    test_llm_model?: string | null
  }
  initialScenarioIds?: string[]
  onCreated: (run: SimulationRun) => void
}

function CheckList({
  items,
  selected,
  onChange,
  emptyText,
}: {
  items: Array<{ id: string; name: string; hint?: string }>
  selected: string[]
  onChange: (ids: string[]) => void
  emptyText: string
}) {
  if (items.length === 0) return <p className="text-sm text-gray-500">{emptyText}</p>
  const allSelected = selected.length === items.length
  return (
    <div className="rounded-lg border border-gray-200">
      <label className="flex items-center gap-2 border-b border-gray-100 px-3 py-2 text-xs font-medium text-gray-600">
        <input
          type="checkbox"
          checked={allSelected}
          onChange={() => onChange(allSelected ? [] : items.map((i) => i.id))}
        />
        Select all ({items.length})
      </label>
      <div className="max-h-48 overflow-y-auto">
        {items.map((item) => (
          <label key={item.id} className="flex items-start gap-2 px-3 py-1.5 text-sm hover:bg-gray-50">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={selected.includes(item.id)}
              onChange={() =>
                onChange(
                  selected.includes(item.id) ? selected.filter((id) => id !== item.id) : [...selected, item.id],
                )
              }
            />
            <span className="min-w-0">
              <span className="block truncate text-gray-900">{item.name}</span>
              {item.hint ? <span className="block truncate text-xs text-gray-500">{item.hint}</span> : null}
            </span>
          </label>
        ))}
      </div>
    </div>
  )
}

export default function NewSimulationRunModal({ isOpen, onClose, agent, initialScenarioIds, onCreated }: Props) {
  const queryClient = useQueryClient()
  const isChat = isChatMedium(agent.call_medium)
  const agentMedium = isChat ? 'chat' : 'voice'
  const listSurface = metricListSurfaceForAgentMedium(agentMedium)
  const chatConn = (agent.chat_connection_type || 'internal_llm').toLowerCase()
  const hostedProduction = isChat && isFullLlmToLlmChatConnection(chatConn)
  const liveChatProduction = isChat && !hostedProduction

  const [step, setStep] = useState(0)
  const { data: scenarios = [] } = useQuery<ScenarioRow[]>({
    queryKey: ['scenarios', 'agent', agent.id],
    queryFn: () => apiClient.listScenarios(0, 500, agent.id),
    enabled: isOpen,
  })
  const { data: toolCatalog = [] } = useQuery({
    queryKey: ['agent-tool-catalog', agent.id],
    queryFn: () => apiClient.getAgentToolCatalog(agent.id),
    enabled: isOpen && !liveChatProduction,
  })
  const { data: allPersonas = [] } = useQuery<PersonaRow[]>({
    queryKey: ['personas'],
    queryFn: () => apiClient.listPersonas(0, 500),
    enabled: isOpen,
  })
  const { data: metrics } = useQuery({
    queryKey: ['metrics', listSurface],
    queryFn: () => apiClient.listMetrics(listSurface, true),
    enabled: isOpen,
  })
  const metricRows = useMemo(
    () => (metrics ?? EMPTY_METRIC_ROWS) as MetricRow[],
    [metrics],
  )

  const personas = useMemo(
    () =>
      allPersonas.filter((p) =>
        !p.simulation_medium ? true : isChat ? p.simulation_medium !== 'voice' : p.simulation_medium !== 'text',
      ),
    [allPersonas, isChat],
  )

  const [name, setName] = useState('')
  const [scenarioIds, setScenarioIds] = useState<string[]>([])
  const [personaIds, setPersonaIds] = useState<string[]>([])
  const [metricIds, setMetricIds] = useState<string[]>([])
  const [goldenOptOut, setGoldenOptOut] = useState<Set<string>>(() => new Set())
  const prevScenarioIdsRef = useRef<string[]>([])
  const [criteria, setCriteria] = useState<MetricSuccessCriterion[]>([])
  const [attempts, setAttempts] = useState(3)
  const [concurrency, setConcurrency] = useState(4)
  const [overrideProduction, setOverrideProduction] = useState(false)
  const [prodProvider, setProdProvider] = useState<ModelProvider | null>(null)
  const [prodModel, setProdModel] = useState('')
  const [overrideTest, setOverrideTest] = useState(false)
  const [testProvider, setTestProvider] = useState<ModelProvider | null>(null)
  const [testModel, setTestModel] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isOpen) return
    setStep(0)
    setError(null)
    setName('')
    setMetricIds([])
    setGoldenOptOut(new Set())
    prevScenarioIdsRef.current = []
    setCriteria([])
    setAttempts(3)
    setConcurrency(4)
    setOverrideProduction(false)
    setOverrideTest(false)
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    setScenarioIds(initialScenarioIds?.length ? initialScenarioIds : scenarios.map((s) => s.id))
  }, [isOpen, scenarios, initialScenarioIds])

  useEffect(() => {
    if (isOpen && personaIds.length === 0 && personas.length > 0) setPersonaIds([personas[0].id])
  }, [isOpen, personas, personaIds.length])

  useEffect(() => {
    if (!isOpen) return
    if (liveChatProduction) setOverrideProduction(false)
  }, [isOpen, liveChatProduction])

  const normalizedMetricIds = useMemo(
    () => normalizeSelectedMetricIds(metricIds, metricRows),
    [metricIds, metricRows],
  )

  useEffect(() => {
    if (!isOpen) return
    setCriteria((prev) => syncCriteriaWithMetrics(metricRows, normalizedMetricIds, prev))
  }, [isOpen, normalizedMetricIds, metricRows])

  const scenarioNameById = useMemo(
    () => new Map(scenarios.map((s) => [s.id, s.name])),
    [scenarios],
  )

  useEffect(() => {
    if (!isOpen || metricRows.length === 0) return
    const added = scenarioIds.filter((id) => !prevScenarioIdsRef.current.includes(id))
    prevScenarioIdsRef.current = scenarioIds
    setMetricIds((prev) =>
      syncSimulationMetricSelection(
        prev,
        metricRows,
        agentMedium,
        agent.id,
        scenarioIds,
        goldenOptOut,
        added,
      ),
    )
  }, [isOpen, scenarioIds, metricRows, agentMedium, goldenOptOut, agent.id])

  const emptyScenarioNames = useMemo(
    () =>
      scenariosWithNoApplicableMetrics(
        scenarios.filter((s) => scenarioIds.includes(s.id)),
        metricRows,
        agentMedium,
        normalizedMetricIds,
        agent.id,
      ),
    [scenarios, scenarioIds, metricRows, agentMedium, normalizedMetricIds, agent.id],
  )

  const agentNameById = useMemo(() => new Map([[agent.id, agent.name]]), [agent.id, agent.name])

  const plannedLlms = useMemo(() => {
    const testDefault = formatLlmPair(agent.test_llm_provider, agent.test_llm_model) || 'Not configured'
    const test = overrideTest && testModel ? formatLlmPair(testProvider, testModel) || testModel : testDefault
    if (liveChatProduction) {
      return {
        production: `Live endpoint (${connectionTypeLabel(agent.chat_connection_type)})`,
        productionHint: 'The customer’s own agent answers. This run does not call a production LLM here.',
        test,
        testHint: overrideTest ? 'Run override' : 'Plays the simulated customer',
      }
    }
    const prodDefault =
      formatLlmPair(agent.main_llm_provider, agent.main_llm_model) ||
      (!isChat ? 'Voice bundle LLM' : 'Not configured')
    const production =
      overrideProduction && prodModel ? formatLlmPair(prodProvider, prodModel) || prodModel : prodDefault
    return {
      production,
      productionHint: overrideProduction ? 'Run override · answers as the agent' : 'Answers as the agent under test',
      test,
      testHint: overrideTest ? 'Run override · plays the customer' : 'Plays the simulated customer',
    }
  }, [
    isChat,
    agent.chat_connection_type,
    agent.main_llm_model,
    agent.main_llm_provider,
    agent.test_llm_model,
    agent.test_llm_provider,
    liveChatProduction,
    overrideProduction,
    overrideTest,
    prodModel,
    prodProvider,
    testModel,
    testProvider,
  ])

  const trials = scenarioIds.length * personaIds.length * attempts

  const createMutation = useMutation({
    mutationFn: () =>
      apiClient.createSimulationRun({
        agent_id: agent.id,
        name: name.trim() || undefined,
        scenario_ids: scenarioIds,
        persona_ids: personaIds,
        metric_ids: normalizedMetricIds,
        metric_success_criteria: criteria,
        n_attempts: attempts,
        n_concurrent: concurrency,
        production_llm_provider: overrideProduction ? prodProvider : null,
        production_llm_model: overrideProduction ? prodModel || null : null,
        test_llm_provider: overrideTest ? testProvider : null,
        test_llm_model: overrideTest ? testModel || null : null,
      }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ['simulation-runs', agent.id] })
      onCreated(run)
    },
    onError: (err) => setError(getApiErrorDetail(err) || 'Failed to start simulation run'),
  })

  const canNext = (): boolean => {
    if (step === 0) return scenarioIds.length > 0 && personaIds.length > 0
    if (step === 1) return normalizedMetricIds.length > 0
    if (step === 2) return criteriaStepValid(criteria, metricRows)
    if (step === 3) {
      return (
        (!overrideProduction || Boolean(prodProvider && prodModel.trim())) &&
        (!overrideTest || Boolean(testProvider && testModel.trim()))
      )
    }
    return false
  }

  const metricById = useMemo(() => {
    const map = new Map<string, MetricRow>()
    for (const m of metricRows) {
      map.set(m.id, m)
      for (const c of m.children || []) map.set(c.id, c)
    }
    return map
  }, [metricRows])

  if (!isOpen) return null

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-gray-500 bg-opacity-75 p-4">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">New simulation run</h3>
            <p className="text-xs text-gray-500">
              Step {step + 1} of {STEPS.length}: {STEPS[step]}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="border-b border-gray-100 px-5 py-2">
          <div className="flex gap-1">
            {STEPS.map((label, idx) => (
              <div
                key={label}
                className={`flex flex-1 items-center justify-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium ${
                  idx === step
                    ? 'bg-primary-50 text-primary-800'
                    : idx < step
                      ? 'text-gray-600'
                      : 'text-gray-400'
                }`}
              >
                {idx < step ? <Check className="h-3.5 w-3.5" /> : null}
                <span className="hidden truncate sm:inline">{label}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {step === 0 ? (
            <div className="space-y-5">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Name <span className="text-gray-400">(optional)</span>
                </label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Refund flows after prompt v3"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <h4 className="mb-1 text-sm font-medium text-gray-700">Scenarios</h4>
                  <CheckList
                    items={scenarios.map((s) => ({ id: s.id, name: s.name, hint: s.description ?? undefined }))}
                    selected={scenarioIds}
                    onChange={setScenarioIds}
                    emptyText="No scenarios for this agent yet. Generate synthetic tests first."
                  />
                </div>
                <div>
                  <h4 className="mb-1 text-sm font-medium text-gray-700">Personas</h4>
                  <CheckList
                    items={personas.map((p) => ({ id: p.id, name: p.name }))}
                    selected={personaIds}
                    onChange={setPersonaIds}
                    emptyText="No personas available."
                  />
                </div>
              </div>
            </div>
          ) : null}

          {step === 1 ? (
            <div>
              <h4 className="mb-1 text-sm font-medium text-gray-700">Metrics to evaluate</h4>
              <p className="mb-3 text-xs text-gray-500">
                Golden metrics apply to every trial. Agent-specific metrics are linked to this
                agent. Pass/fail rules are configured on the next step.
              </p>
              <SimulationMetricPicker
                metricRows={metricRows}
                agentMedium={agentMedium}
                runAgentId={agent.id}
                selectedScenarioIds={scenarioIds}
                scenarioNameById={scenarioNameById}
                agentNameById={agentNameById}
                selectedMetricIds={metricIds}
                goldenOptOut={goldenOptOut}
                onGoldenOptOutChange={setGoldenOptOut}
                onChange={setMetricIds}
              />
            </div>
          ) : null}

          {step === 2 ? (
            <MetricSuccessCriteriaStep
              metrics={metricRows}
              selectedMetricIds={normalizedMetricIds}
              criteria={criteria}
              onChange={setCriteria}
              scenarioNameById={scenarioNameById}
            />
          ) : null}

          {step === 3 ? (
            <div className="space-y-5">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <label className="block text-sm">
                  <span className="mb-1 block font-medium text-gray-700">Attempts per scenario</span>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={attempts}
                    onChange={(e) => setAttempts(Math.min(10, Math.max(1, Number(e.target.value) || 1)))}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2"
                  />
                  <span className="mt-1 block text-xs text-gray-500">More than 1 measures consistency (pass^k).</span>
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block font-medium text-gray-700">Concurrent trials</span>
                  <input
                    type="number"
                    min={1}
                    max={32}
                    value={concurrency}
                    onChange={(e) => setConcurrency(Math.min(32, Math.max(1, Number(e.target.value) || 1)))}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2"
                  />
                </label>
              </div>

              <dl className="grid gap-2 sm:grid-cols-2">
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                  <dt className="text-xs font-medium text-gray-500">Production agent LLM</dt>
                  <dd className="mt-0.5 font-mono text-sm text-gray-900">{plannedLlms.production}</dd>
                  <dd className="text-[11px] text-gray-500">{plannedLlms.productionHint}</dd>
                </div>
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                  <dt className="text-xs font-medium text-gray-500">Test agent LLM</dt>
                  <dd className="mt-0.5 font-mono text-sm text-gray-900">{plannedLlms.test}</dd>
                  <dd className="text-[11px] text-gray-500">{plannedLlms.testHint}</dd>
                </div>
              </dl>

              <div className="space-y-3">
                {!liveChatProduction ? (
                  <>
                    <label className="flex items-center gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={overrideProduction}
                        onChange={(e) => setOverrideProduction(e.target.checked)}
                      />
                      Override production agent LLM
                    </label>
                    {overrideProduction ? (
                      <EvaluatorLlmPicker
                        title="Production agent LLM"
                        description="Runs the agent's prompt on this model instead (hosted chat agents only)."
                        llmProvider={prodProvider}
                        llmModel={prodModel}
                        onProviderChange={setProdProvider}
                        onModelChange={setProdModel}
                      />
                    ) : null}
                  </>
                ) : null}
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input type="checkbox" checked={overrideTest} onChange={(e) => setOverrideTest(e.target.checked)} />
                  Override test agent LLM
                </label>
                {overrideTest ? (
                  <EvaluatorLlmPicker
                    title="Test agent LLM"
                    description="Model that plays the simulated customer."
                    llmProvider={testProvider}
                    llmModel={testModel}
                    onProviderChange={setTestProvider}
                    onModelChange={setTestModel}
                  />
                ) : null}
              </div>

              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                <h4 className="text-sm font-semibold text-gray-900">Review</h4>
                <p className="mt-1 text-sm text-gray-600">
                  {scenarioIds.length} scenario{scenarioIds.length !== 1 ? 's' : ''} × {personaIds.length} persona
                  {personaIds.length !== 1 ? 's' : ''} × {attempts} attempt{attempts !== 1 ? 's' : ''} ={' '}
                  <span className="font-semibold text-gray-900">{trials} trials</span>
                </p>
                <p className="mt-2 text-xs text-gray-500">
                  Each trial passes only when every metric below meets its success rule.
                </p>
                {toolCatalog.length ? (
                  <p className="mt-2 text-xs text-gray-600">
                    Production agent tools: {toolCatalog.filter((t) => t.simulation_behavior === 'live').length} live,{' '}
                    {toolCatalog.filter((t) => t.simulation_behavior === 'mocked').length} mocked
                    <span className="text-gray-500"> ({toolCatalog.map((t) => t.name).join(', ')})</span>
                  </p>
                ) : null}
                {emptyScenarioNames.length > 0 ? (
                  <p className="mt-2 rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
                    No selected metrics apply to: {emptyScenarioNames.join(', ')}. Those scenarios will not
                    be scored.
                  </p>
                ) : null}
                <ul className="mt-3 space-y-2 text-sm">
                  {criteria.map((c) => {
                    const metric = metricById.get(c.metric_id)
                    return (
                      <li key={c.metric_id} className="border-t border-gray-200 pt-2 first:border-0 first:pt-0">
                        <span className="font-medium text-gray-900">{metric?.name ?? c.metric_id}</span>
                        {metric && !isGoldenMetric(metric) ? (
                          <span className="mt-0.5 block text-xs text-gray-500">
                            Scored only on: {formatMetricScopeLabel(metric, scenarioNameById)}
                          </span>
                        ) : null}
                        <span className="mt-0.5 block text-xs text-gray-600">
                          {metric ? formatCriterionSummary(c, metric) : '—'}
                        </span>
                      </li>
                    )
                  })}
                </ul>
              </div>
            </div>
          ) : null}

          {error ? <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-gray-200 px-5 py-4">
          <Button
            variant="outline"
            onClick={() => (step === 0 ? onClose() : setStep(step - 1))}
            leftIcon={step > 0 ? <ChevronLeft className="h-4 w-4" /> : undefined}
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
            <Button
              variant="primary"
              onClick={() => {
                setError(null)
                createMutation.mutate()
              }}
              disabled={!canNext()}
              isLoading={createMutation.isPending}
              leftIcon={<Play className="h-4 w-4" />}
            >
              Start run
            </Button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
