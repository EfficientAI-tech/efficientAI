import { Link } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import ClusterScopeInfo from './ClusterScopeInfo'
import type { MetricClustersClient } from './clients'
import type {
  EvaluationMetricClustersState,
  EvaluatorResultsAgentSummary,
} from './types'
import type { EvaluatorResultClusterScope } from './clients'

export default function ClusterReportDetailsTab({
  state,
  client,
  agents = [],
  urlScope = null,
}: {
  state: EvaluationMetricClustersState
  client: MetricClustersClient
  agents?: EvaluatorResultsAgentSummary[]
  urlScope?: EvaluatorResultClusterScope | null
}) {
  return (
    <div className="space-y-4">
      <ClusterScopeInfo state={state} agents={agents} urlScope={urlScope} />

      <article className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
        <div>
          <h3 className="text-base font-semibold text-gray-900">
            Failure metrics
          </h3>
          <p className="text-sm text-gray-600 mt-1">
            Per-metric clusters of flagged calls with gap labels and
            sub-categories.
          </p>
        </div>

        {state.groups.map((group) => {
          const clusters = [...group.clusters].sort(
            (a, b) => b.count - a.count || a.label.localeCompare(b.label),
          )
          const categorizedCalls = clusters.reduce(
            (sum, cluster) => sum + Math.max(0, cluster.count || 0),
            0,
          )
          const totalFlagged = Math.max(0, group.flagged_count || 0)

          return (
            <article
              key={group.metric_id}
              className="rounded-lg border border-gray-200 bg-white overflow-hidden"
            >
              <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80">
                <h4 className="text-base font-semibold text-gray-900">
                  {group.metric_name}
                </h4>
                <p className="text-xs text-gray-500">
                  {group.flagged_count} flagged calls · {clusters.length}{' '}
                  cluster{clusters.length === 1 ? '' : 's'}
                  {state.failure_policies?.[group.metric_id] ? (
                    <>
                      {' '}
                      · failure:{' '}
                      {[
                        ...(state.failure_policies[group.metric_id]
                          .failure_values || []),
                        ...(state.failure_policies[group.metric_id]
                          .failure_child_names || []),
                      ].join(', ') || 'numeric rule'}
                    </>
                  ) : null}
                </p>
                {group.failure_reason ? (
                  <p className="text-xs text-gray-600 mt-1">
                    <span className="font-semibold text-gray-700">
                      Why flagged:
                    </span>{' '}
                    {group.failure_reason}
                  </p>
                ) : null}
              </div>
              <div className="p-4 space-y-3">
                <div className="rounded-md border border-gray-100 bg-gray-50/60 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
                      Cluster breakdown
                    </p>
                    <span className="text-xs font-semibold text-gray-700">
                      {categorizedCalls} / {totalFlagged}
                    </span>
                  </div>
                </div>
                {clusters.map((cluster) => {
                  const exampleHref = client.buildEvidenceHref(cluster.evidence)
                  return (
                    <div
                      key={cluster.id}
                      className="rounded-md border border-gray-100 p-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm font-semibold text-gray-900">
                          {cluster.label}
                        </p>
                        <span className="text-xs font-bold uppercase text-primary-700">
                          {cluster.gap_label.replace(/_/g, ' ')}
                        </span>
                      </div>
                      <p className="text-xs text-gray-600 mt-0.5">
                        {cluster.count} calls · {cluster.share_pct.toFixed(1)}%
                        share
                      </p>
                      {cluster.failure_reason ? (
                        <p className="text-xs text-gray-600 mt-1">
                          <span className="font-semibold">Why flagged:</span>{' '}
                          {cluster.failure_reason}
                        </p>
                      ) : null}
                      {group.flagged_count > 0 ? (
                        <div className="mt-2">
                          <div className="h-2.5 w-full rounded bg-primary-100 overflow-hidden">
                            <div
                              className="h-full rounded bg-primary-500"
                              style={{
                                width: `${Math.min(
                                  100,
                                  (cluster.count / group.flagged_count) * 100,
                                ).toFixed(1)}%`,
                              }}
                            />
                          </div>
                        </div>
                      ) : null}
                      {cluster.observation ? (
                        <p className="text-sm text-gray-700 mt-2">
                          {cluster.observation}
                        </p>
                      ) : null}
                      {cluster.sub_clusters.length ? (
                        <ul className="mt-2 text-xs text-gray-600 list-disc pl-4">
                          {cluster.sub_clusters.map((sub) => (
                            <li key={sub.label}>
                              {sub.label} — {sub.count} (
                              {sub.share_pct.toFixed(1)}%)
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {cluster.evidence.quote ||
                      cluster.evidence.turns?.length ||
                      cluster.evidence.conversation_id ? (
                        <div className="mt-2 rounded-md bg-gray-50 border border-gray-100 p-2 space-y-1">
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-600">
                            Example call
                          </p>
                          {cluster.evidence.turns?.length ? (
                            cluster.evidence.turns.map((turn, i) => (
                              <p key={i} className="text-xs text-gray-800">
                                <span className="font-semibold text-primary-700">
                                  {turn.speaker}:
                                </span>{' '}
                                {turn.text}
                              </p>
                            ))
                          ) : cluster.evidence.quote ? (
                            <p className="text-xs text-gray-800">
                              {cluster.evidence.quote}
                            </p>
                          ) : null}
                          {exampleHref && cluster.evidence.conversation_id ? (
                            <Link
                              to={exampleHref}
                              className="inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:text-primary-800"
                            >
                              <ExternalLink className="h-3 w-3" />
                              {cluster.evidence.conversation_id}
                            </Link>
                          ) : cluster.evidence.conversation_id ? (
                            <p className="text-[10px] text-gray-500 font-mono">
                              {cluster.evidence.conversation_id}
                            </p>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </article>
          )
        })}
      </article>
    </div>
  )
}
