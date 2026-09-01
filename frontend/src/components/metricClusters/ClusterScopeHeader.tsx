import { CalendarDays, Phone, Sparkles } from 'lucide-react'
import Button from '../Button'
import { formatResultsDateRange } from '../../pages/evaluators/results/resultsDateRange'
import type {
  EvaluationMetricClustersState,
  EvaluatorResultsAgentSummary,
  MetricClusterGenerationScope,
} from './types'
import type { EvaluatorResultClusterScope } from './clients'

const PROVIDER_DISPLAY: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  deepseek: 'DeepSeek',
  groq: 'Groq',
}

export interface ClusterScopeDisplay {
  agentName: string
  scenarioNames: string[]
  dateLabel: string
  eligibleCallCount: number | null
  selectedCallCount: number | null
}

export function resolveClusterScopeDisplay(
  state: EvaluationMetricClustersState | null,
  agents: EvaluatorResultsAgentSummary[],
  urlScope: EvaluatorResultClusterScope | null,
): ClusterScopeDisplay | null {
  const fromApi = state?.generation_scope
  if (fromApi?.agent_id) {
    return {
      agentName: fromApi.agent_name ?? 'Agent',
      scenarioNames: fromApi.scenario_names ?? [],
      dateLabel: formatScopeDateLabel(fromApi.since, fromApi.until),
      eligibleCallCount: fromApi.eligible_call_count ?? null,
      selectedCallCount: fromApi.selected_call_count ?? null,
    }
  }

  if (!urlScope?.agentId) return null
  const agent = agents.find((item) => item.agent_id === urlScope.agentId)
  const agentName = agent?.agent_name ?? 'Agent'

  const scenarioNames: string[] = []
  if (urlScope.scenarioIds?.length && agent) {
    const nameById = new Map<string, string>()
    for (const suite of agent.suites ?? []) {
      for (const scenario of suite.scenarios ?? []) {
        nameById.set(scenario.scenario_id, scenario.scenario_name)
      }
    }
    for (const id of urlScope.scenarioIds) {
      scenarioNames.push(nameById.get(id) ?? id)
    }
  }

  let dateLabel = 'All time'
  if (urlScope.since && urlScope.until) {
    try {
      dateLabel = formatResultsDateRange(
        urlScope.since.slice(0, 10),
        urlScope.until.slice(0, 10),
      )
    } catch {
      dateLabel = 'Custom range'
    }
  }

  const selectedCallCount =
    state?.selected_evaluation_row_ids?.length ??
    state?.generation_scope?.selected_call_count ??
    null

  return {
    agentName,
    scenarioNames,
    dateLabel,
    eligibleCallCount: null,
    selectedCallCount,
  }
}

function formatScopeDateLabel(
  since?: string | null,
  until?: string | null,
): string {
  if (!since && !until) return 'All time'
  if (since && until) {
    try {
      return formatResultsDateRange(since.slice(0, 10), until.slice(0, 10))
    } catch {
      return 'Custom range'
    }
  }
  return 'Custom range'
}

function formatGeneratedAt(value?: string | null): string | null {
  if (!value) return null
  try {
    return new Date(value).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  } catch {
    return value
  }
}

export interface ClusterScopeHeaderProps {
  state: EvaluationMetricClustersState | null
  agents?: EvaluatorResultsAgentSummary[]
  urlScope?: EvaluatorResultClusterScope | null
  onChangeScope?: () => void
  variant?: 'full' | 'placeholder'
}

export default function ClusterScopeHeader({
  state,
  agents = [],
  urlScope = null,
  onChangeScope,
  variant = 'full',
}: ClusterScopeHeaderProps) {
  if (variant === 'placeholder') {
    return (
      <article className="rounded-lg border border-dashed border-gray-200 bg-white px-4 py-3">
        <p className="text-sm font-semibold text-gray-900 mb-1">
          Cluster report scope
        </p>
        <p className="text-sm text-gray-600">
          Pick an agent in Generate clusters to view or create a report for that
          scope. Each agent, scenario set, and date range gets its own report.
        </p>
        {onChangeScope ? (
          <div className="mt-3">
            <Button variant="primary" onClick={onChangeScope}>
              Generate clusters
            </Button>
          </div>
        ) : null}
      </article>
    )
  }

  const display = resolveClusterScopeDisplay(state, agents, urlScope)
  if (!display) return null

  const generatedAt = formatGeneratedAt(state?.generated_at)
  const providerLabel = state?.provider
    ? PROVIDER_DISPLAY[state.provider] || state.provider
    : null
  const modelLabel = state?.model ?? null
  const callsLabel =
    display.eligibleCallCount != null && display.selectedCallCount != null
      ? `${display.selectedCallCount.toLocaleString()} selected · ${display.eligibleCallCount.toLocaleString()} eligible`
      : display.selectedCallCount != null
        ? `${display.selectedCallCount.toLocaleString()} selected call${display.selectedCallCount === 1 ? '' : 's'}`
        : null

  return (
    <article className="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-base font-semibold text-gray-900">
              {display.agentName}
            </p>
            {state?.is_stale ? (
              <span className="inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
                Stale
              </span>
            ) : null}
            {state?.status === 'running' ? (
              <span className="inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
                Generating
              </span>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-600">
            <span className="inline-flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-gray-400 shrink-0" />
              {display.scenarioNames.length ? (
                <span className="flex flex-wrap gap-1">
                  {display.scenarioNames.map((name) => (
                    <span
                      key={name}
                      className="inline-flex rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] font-medium text-gray-700"
                    >
                      {name}
                    </span>
                  ))}
                </span>
              ) : (
                <span className="font-medium text-gray-700">All scenarios</span>
              )}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <CalendarDays className="h-3.5 w-3.5 text-gray-400 shrink-0" />
              {display.dateLabel}
            </span>
            {callsLabel ? (
              <span className="inline-flex items-center gap-1.5 tabular-nums">
                <Phone className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                {callsLabel}
              </span>
            ) : null}
          </div>

          {generatedAt || providerLabel || modelLabel ? (
            <p className="text-[10px] text-gray-500">
              {generatedAt ? `Generated ${generatedAt}` : null}
              {providerLabel || modelLabel ? (
                <>
                  {generatedAt ? ' · ' : null}
                  {providerLabel || 'LLM'}
                  {modelLabel ? ` · ${modelLabel}` : ''}
                </>
              ) : null}
            </p>
          ) : null}
        </div>

        {onChangeScope ? (
          <Button variant="outline" className="shrink-0" onClick={onChangeScope}>
            Change scope
          </Button>
        ) : null}
      </div>
    </article>
  )
}

export type { MetricClusterGenerationScope }
