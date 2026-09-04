import ClusterOverviewCharts from './ClusterOverviewCharts'
import MetricClustersRcaSummaryPanel from './MetricClustersRcaSummaryPanel'
import type { EvaluationMetricClustersState } from './types'

function clampProseToSentences(
  text: string,
  maxSentences = 3,
  maxChars = 300,
): string {
  const trimmed = text.trim().replace(/\s*\n+\s*/g, ' ')
  if (!trimmed) return trimmed
  const sentences = trimmed.split(/(?<=[.!?])\s+/).filter(Boolean)
  let result = (sentences.length ? sentences.slice(0, maxSentences) : [trimmed])
    .join(' ')
    .trim()
  if (result.length > maxChars) {
    const cut = result.slice(0, maxChars - 3).replace(/\s+\S*$/, '')
    result = `${cut || result.slice(0, maxChars)}...`
  }
  return result
}

export default function ClusterReportVisualizationTab({
  state,
}: {
  state: EvaluationMetricClustersState
}) {
  return (
    <div className="space-y-4">
      {state.overview ? (
        <article className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">Overview</h3>
          <p className="text-sm text-gray-700 leading-relaxed">
            {clampProseToSentences(state.overview)}
          </p>
        </article>
      ) : null}

      <article className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
        <ClusterOverviewCharts state={state} />
        {state.rca_summary ? (
          <MetricClustersRcaSummaryPanel summary={state.rca_summary} />
        ) : null}
      </article>

      {state.discovered_problems.length ? (
        <article className="rounded-lg border border-dashed border-primary-200 bg-primary-50/30 p-4">
          <h4 className="text-base font-semibold text-gray-900 mb-2">
            Proactive problem discovery
          </h4>
          <div className="space-y-2">
            {state.discovered_problems.map((item) => (
              <div key={item.id} className="text-sm text-gray-800">
                <span className="font-semibold">{item.label}</span>
                <span className="text-primary-700 ml-2 uppercase text-xs font-semibold">
                  {item.gap_label.replace(/_/g, ' ')}
                </span>
                <span className="text-gray-500 ml-2">
                  {item.count} · {item.share_pct.toFixed(1)}%
                </span>
                {item.observation ? (
                  <p className="mt-1 text-gray-600">{item.observation}</p>
                ) : null}
              </div>
            ))}
          </div>
        </article>
      ) : null}
    </div>
  )
}

export { clampProseToSentences }
