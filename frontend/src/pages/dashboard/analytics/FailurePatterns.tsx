import { Link } from 'react-router-dom'
import type { DashboardCluster } from './dashboardClusters'

export default function FailurePatterns({
  clusters,
  agentId,
  metricId,
}: {
  clusters: DashboardCluster[]
  agentId: string | null
  metricId: string
}) {
  if (clusters.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-gray-200 bg-white px-4 py-8 text-sm text-gray-500">
        No concentrated failure pattern in this window.
      </div>
    )
  }
  const majority = clusters[0]
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">Failure patterns</h3>
        <p className="text-xs text-gray-500 mt-0.5">Ranked by share of failing calls. The top cluster drives the prompt fix.</p>
      </div>
      <ul className="space-y-2">
        {clusters.map((cluster, index) => (
          <li key={cluster.id} className="rounded-xl border border-gray-200 bg-white px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-gray-900">
                  {index === 0 ? 'Majority · ' : ''}
                  {cluster.label}
                </p>
                <p className="mt-0.5 text-xs text-gray-600">{cluster.observation}</p>
              </div>
              <div className="text-right text-xs tabular-nums text-gray-500">
                {cluster.count} · {cluster.sharePct}%
                {cluster.gapLabel && <div className="mt-0.5 uppercase tracking-wide">{cluster.gapLabel}</div>}
              </div>
            </div>
            {cluster.evidence && (
              <p className="mt-2 border-l-2 border-gray-200 pl-2 text-xs italic text-gray-500">{cluster.evidence}</p>
            )}
          </li>
        ))}
      </ul>
      <div className="rounded-xl border border-indigo-200 bg-indigo-50/60 p-4">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-indigo-800">Prompt fix</p>
        <p className="mt-1 text-sm font-medium text-gray-900">{majority.label}</p>
        <p className="mt-1 text-sm text-gray-700">{majority.suggestedPrompt}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Link
            to={`/prompts/optimization${agentId ? `?agent=${encodeURIComponent(agentId)}` : ''}`}
            className="rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
          >
            Open optimization
          </Link>
          <Link
            to={`/results?tab=clusters&cluster_agent=${encodeURIComponent(agentId ?? 'mock-agent-support-eu')}&metric=${encodeURIComponent(metricId)}`}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-800 hover:bg-gray-50"
          >
            Open failure patterns
          </Link>
        </div>
      </div>
    </div>
  )
}
