import { CalendarDays, Phone, Sparkles } from 'lucide-react'
import { resolveClusterScopeDisplay } from './ClusterScopeHeader'
import type {
  EvaluationMetricClustersState,
  EvaluatorResultsAgentSummary,
} from './types'
import type { EvaluatorResultClusterScope } from './clients'

const PROVIDER_DISPLAY: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  deepseek: 'DeepSeek',
  groq: 'Groq',
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

export default function ClusterScopeInfo({
  state,
  agents = [],
  urlScope = null,
}: {
  state: EvaluationMetricClustersState
  agents?: EvaluatorResultsAgentSummary[]
  urlScope?: EvaluatorResultClusterScope | null
}) {
  const display = resolveClusterScopeDisplay(state, agents, urlScope)
  if (!display) return null

  const generatedAt = formatGeneratedAt(state.generated_at)
  const providerLabel = state.provider
    ? PROVIDER_DISPLAY[state.provider] || state.provider
    : null
  const modelLabel = state.model ?? null
  const callsLabel =
    display.eligibleCallCount != null && display.selectedCallCount != null
      ? `${display.selectedCallCount.toLocaleString()} selected · ${display.eligibleCallCount.toLocaleString()} eligible`
      : display.selectedCallCount != null
        ? `${display.selectedCallCount.toLocaleString()} selected call${display.selectedCallCount === 1 ? '' : 's'}`
        : null

  return (
    <article className="rounded-lg border border-gray-200 bg-white px-4 py-3">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-base font-semibold text-gray-900">
            {display.agentName}
          </p>
          {state.is_stale ? (
            <span className="inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
              Stale
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
    </article>
  )
}
