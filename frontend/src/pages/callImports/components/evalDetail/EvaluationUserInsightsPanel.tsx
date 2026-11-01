import type {
  EvaluationUserInsightItem,
  EvaluationUserInsightsState,
} from '../../../../types/api'
import { clampProseToSentences } from './evalDisplayUtils'

function EvaluationUserInsightsPanel({
  state,
  isLoading,
}: {
  state: EvaluationUserInsightsState | null
  isLoading: boolean
}) {
  if (isLoading || !state || state.status === 'running' || state.status === 'failed') {
    return null
  }

  if (state.status === 'idle') {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50/60 p-4">
        <p className="text-xs text-gray-500">
          User insights generate automatically in the background when you
          click Generate summary above.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs text-gray-500">
          LLM-identified patterns for section 03 of the external audit report.
          {state.max_llm_calls ? (
            <span className="block mt-0.5">
              Sample size: up to {state.max_llm_calls} LLM calls.
            </span>
          ) : null}
        </p>
        {state.is_stale ? (
          <p className="text-[11px] text-amber-700 mt-1">
            More rows completed since these insights were generated. Regenerate
            the summary to refresh.
          </p>
        ) : null}
      </div>
      {state.overview ? (
        <p className="text-xs text-gray-600 break-words leading-relaxed">
          {clampProseToSentences(state.overview)}
        </p>
      ) : null}
      {state.insights.map((insight, index) => (
        <GeneratedUserInsightCard key={insight.id} insight={insight} index={index + 1} />
      ))}
    </div>
  )
}

function GeneratedUserInsightCard({
  insight,
  index,
}: {
  insight: EvaluationUserInsightItem
  index: number
}) {
  const maxCount = Math.max(
    ...insight.categories.map((c) => c.count),
    1,
  )
  return (
    <article className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80">
        <h4 className="text-sm font-semibold text-gray-900">
          3.{index} {insight.title}
        </h4>
        <p className="text-[10px] text-gray-500">pattern-analysis · LLM-identified</p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 lg:divide-x divide-gray-100">
        <div className="p-4 overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-100">
                <th className="pb-2 pr-3 font-medium">Category</th>
                <th className="pb-2 pr-3 font-medium">Share</th>
                <th className="pb-2 pr-3 font-medium">Distribution</th>
                <th className="pb-2 font-medium">Calls</th>
              </tr>
            </thead>
            <tbody>
              {insight.categories.map((cat) => (
                <tr key={cat.label} className="border-b border-gray-50">
                  <td className="py-2 pr-3 text-gray-800">{cat.label}</td>
                  <td className="py-2 pr-3 text-gray-600">{cat.share_pct.toFixed(1)}%</td>
                  <td className="py-2 pr-3">
                    <div className="h-2 w-24 rounded bg-gray-100 overflow-hidden">
                      <div
                        className="h-full bg-gray-800 rounded"
                        style={{
                          width: `${Math.min(100, (cat.count / maxCount) * 100)}%`,
                        }}
                      />
                    </div>
                  </td>
                  <td className="py-2 text-gray-600">{cat.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="p-4 space-y-3">
          <div className="rounded-md bg-rose-50/80 border border-rose-100 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-rose-800 mb-1">
              Observation
            </p>
            <p className="text-xs text-gray-800 leading-relaxed">{insight.observation}</p>
          </div>
          <div className="rounded-md bg-amber-50/60 border border-amber-100 p-3 space-y-2">
            {insight.evidence.turns?.length ? (
              insight.evidence.turns.map((turn, i) => (
                <p key={i} className="text-xs text-gray-800">
                  <span className="font-semibold text-rose-700">{turn.speaker}:</span>{' '}
                  {turn.text}
                </p>
              ))
            ) : insight.evidence.quote ? (
              <p className="text-xs text-gray-800">
                <span className="font-semibold text-rose-700">User:</span>{' '}
                {insight.evidence.quote}
              </p>
            ) : null}
            {insight.evidence.conversation_id ? (
              <p className="text-[10px] text-gray-500">
                {insight.evidence.conversation_id}
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </article>
  )
}

export { EvaluationUserInsightsPanel }
