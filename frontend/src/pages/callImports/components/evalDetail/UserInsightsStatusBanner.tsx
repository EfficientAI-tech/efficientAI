import { Loader2 } from 'lucide-react'
import type { EvaluationUserInsightsState } from '../../../../types/api'

function UserInsightsStatusBanner({
  state,
  isLoading,
}: {
  state: EvaluationUserInsightsState | null
  isLoading: boolean
}) {
  if (isLoading) {
    return (
      <section className="mt-4 rounded-lg border border-gray-200 bg-white px-4 py-3">
        <p className="text-xs text-gray-500 inline-flex items-center gap-1.5">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading user insights…
        </p>
      </section>
    )
  }

  if (!state || state.status === 'idle' || state.status === 'completed') {
    return null
  }

  if (state.status === 'running') {
    const completed = state.progress?.completed_llm_calls ?? 0
    const total = state.progress?.total_llm_calls ?? 0
    const pct = total > 0 ? Math.round((completed / total) * 100) : 0
    return (
      <section className="mt-4 rounded-lg border border-primary-200 bg-primary-50/40 px-4 py-3">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
          <p className="text-xs font-semibold text-gray-900 inline-flex items-center gap-1.5">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary-600" />
            AI User Insights — identifying patterns from rationales and transcripts…
          </p>
          {total > 0 ? (
            <p className="text-[10px] text-gray-500 tabular-nums">
              {completed} / {total} LLM calls ({pct}%)
            </p>
          ) : null}
        </div>
        {total > 0 ? (
          <div>
            <div className="h-2 rounded-full bg-primary-100 overflow-hidden">
              <div
                className="h-full bg-primary-600 transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
            {state.max_llm_calls ? (
              <p className="text-[10px] text-gray-500 mt-1">
                Sample budget: {state.max_llm_calls} LLM calls
              </p>
            ) : null}
          </div>
        ) : null}
      </section>
    )
  }

  return (
    <section className="mt-4 rounded-lg border border-red-200 bg-red-50/50 px-4 py-3">
      <p className="text-xs font-semibold text-gray-900 mb-1">
        AI User Insights generation failed
      </p>
      <p className="text-xs text-red-700">
        {state.error_message || 'User insights generation failed.'}
      </p>
      <p className="text-[11px] text-gray-500 mt-1">
        Click Regenerate on the summary card to retry.
      </p>
    </section>
  )
}

export { UserInsightsStatusBanner }
