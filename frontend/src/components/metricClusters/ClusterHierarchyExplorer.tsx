import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ChevronDown,
  ChevronRight,
  Copy,
  ExternalLink,
  Search,
} from 'lucide-react'
import type { MetricClustersClient } from './clients'
import type {
  EvaluationMetricClustersState,
  MetricCluster,
  MetricClusterGroup,
  MetricSubCluster,
} from '../../types/api'

type TreeSelection =
  | { kind: 'metric'; group: MetricClusterGroup }
  | { kind: 'cluster'; group: MetricClusterGroup; cluster: MetricCluster }
  | {
      kind: 'subcluster'
      group: MetricClusterGroup
      cluster: MetricCluster
      sub: MetricSubCluster
    }

function shortId(id: string): string {
  return id.slice(0, 8)
}

function copyToClipboard(text: string) {
  void navigator.clipboard?.writeText(text)
}

function gapBadgeClass(): string {
  return 'inline-flex rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-primary-700 bg-primary-50'
}

export default function ClusterHierarchyExplorer({
  state,
  client,
}: {
  state: EvaluationMetricClustersState
  client: MetricClustersClient
}) {
  const [search, setSearch] = useState('')
  const [expandedMetrics, setExpandedMetrics] = useState<Set<string>>(() => new Set())
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(() => new Set())
  const [selection, setSelection] = useState<TreeSelection | null>(null)

  const groups = state.groups

  useEffect(() => {
    if (!groups.length) {
      setSelection(null)
      return
    }
    const first = groups[0]
    const clusters = [...first.clusters].sort(
      (a, b) => b.count - a.count || a.label.localeCompare(b.label),
    )
    setExpandedMetrics(new Set([first.metric_id]))
    if (clusters[0]) {
      setExpandedClusters(new Set([clusters[0].id]))
      setSelection({ kind: 'cluster', group: first, cluster: clusters[0] })
    } else {
      setSelection({ kind: 'metric', group: first })
    }
  }, [state.generated_at, groups.length])

  const filteredGroups = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return groups
    return groups
      .map((group) => {
        const metricMatch =
          group.metric_name.toLowerCase().includes(q) ||
          group.metric_id.toLowerCase().includes(q)
        const clusters = group.clusters.filter((cluster) => {
          const clusterMatch =
            cluster.label.toLowerCase().includes(q) ||
            cluster.id.toLowerCase().includes(q) ||
            cluster.gap_label.toLowerCase().includes(q)
          const subMatch = cluster.sub_clusters.some((sub) =>
            sub.label.toLowerCase().includes(q),
          )
          return clusterMatch || subMatch
        })
        if (metricMatch || clusters.length) {
          return { ...group, clusters: metricMatch ? group.clusters : clusters }
        }
        return null
      })
      .filter(Boolean) as MetricClusterGroup[]
  }, [groups, search])

  const toggleMetric = (metricId: string) => {
    setExpandedMetrics((prev) => {
      const next = new Set(prev)
      if (next.has(metricId)) next.delete(metricId)
      else next.add(metricId)
      return next
    })
  }

  const toggleCluster = (clusterId: string) => {
    setExpandedClusters((prev) => {
      const next = new Set(prev)
      if (next.has(clusterId)) next.delete(clusterId)
      else next.add(clusterId)
      return next
    })
  }

  return (
    <article className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80 space-y-3">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Cluster hierarchy</h3>
          <p className="text-sm text-gray-600 mt-0.5">
            Metric → level-1 cluster (with ID) → sub-clusters from LLM synthesis.
          </p>
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by label or cluster ID…"
            className="w-full rounded-md border border-gray-200 bg-white py-1.5 pl-8 pr-3 text-sm"
          />
        </div>
      </div>

      <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] divide-y lg:divide-y-0 lg:divide-x divide-gray-100">
        <div className="p-3 max-h-[520px] overflow-y-auto space-y-1">
          {filteredGroups.length === 0 ? (
            <p className="text-sm text-gray-500 px-2 py-4">No clusters match your search.</p>
          ) : (
            filteredGroups.map((group) => {
              const metricOpen = expandedMetrics.has(group.metric_id)
              const clusters = [...group.clusters].sort(
                (a, b) => b.count - a.count || a.label.localeCompare(b.label),
              )
              return (
                <div key={group.metric_id}>
                  <button
                    type="button"
                    onClick={() => {
                      toggleMetric(group.metric_id)
                      setSelection({ kind: 'metric', group })
                    }}
                    className={`w-full flex items-start gap-1.5 rounded-md px-2 py-1.5 text-left text-sm hover:bg-gray-50 ${
                      selection?.kind === 'metric' && selection.group.metric_id === group.metric_id
                        ? 'bg-primary-50 ring-1 ring-primary-200'
                        : ''
                    }`}
                  >
                    {metricOpen ? (
                      <ChevronDown className="h-4 w-4 shrink-0 text-gray-400 mt-0.5" />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0 text-gray-400 mt-0.5" />
                    )}
                    <span className="min-w-0">
                      <span className="font-semibold text-gray-900">{group.metric_name}</span>
                      <span className="block text-[10px] text-gray-500 mt-0.5">
                        {group.flagged_count} flagged · {clusters.length} cluster
                        {clusters.length === 1 ? '' : 's'}
                      </span>
                    </span>
                  </button>
                  {metricOpen ? (
                    <div className="ml-5 border-l border-gray-100 pl-2 space-y-0.5">
                      {clusters.map((cluster) => {
                        const clusterOpen = expandedClusters.has(cluster.id)
                        const hasSubs = cluster.sub_clusters.length > 0
                        return (
                          <div key={cluster.id}>
                            <button
                              type="button"
                              onClick={() => {
                                if (hasSubs) toggleCluster(cluster.id)
                                setSelection({ kind: 'cluster', group, cluster })
                              }}
                              className={`w-full flex items-start gap-1 rounded-md px-2 py-1.5 text-left text-xs hover:bg-gray-50 ${
                                selection?.kind === 'cluster' &&
                                selection.cluster.id === cluster.id
                                  ? 'bg-primary-50 ring-1 ring-primary-200'
                                  : ''
                              }`}
                            >
                              {hasSubs ? (
                                clusterOpen ? (
                                  <ChevronDown className="h-3.5 w-3.5 shrink-0 text-gray-400 mt-0.5" />
                                ) : (
                                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-gray-400 mt-0.5" />
                                )
                              ) : (
                                <span className="w-3.5 shrink-0" />
                              )}
                              <span className="min-w-0 flex-1">
                                <span className="font-medium text-gray-900">{cluster.label}</span>
                                <span className="flex flex-wrap items-center gap-1.5 mt-0.5">
                                  <code className="text-[10px] font-mono text-gray-500 bg-gray-100 px-1 rounded">
                                    {shortId(cluster.id)}
                                  </code>
                                  <span className={gapBadgeClass()}>
                                    {cluster.gap_label.replace(/_/g, ' ')}
                                  </span>
                                  <span className="text-[10px] text-gray-500 tabular-nums">
                                    {cluster.count} · {cluster.share_pct.toFixed(1)}%
                                  </span>
                                </span>
                              </span>
                            </button>
                            {hasSubs && clusterOpen ? (
                              <div className="ml-4 border-l border-gray-100 pl-2">
                                {cluster.sub_clusters.map((sub) => (
                                  <button
                                    key={sub.id ?? sub.label}
                                    type="button"
                                    onClick={() =>
                                      setSelection({
                                        kind: 'subcluster',
                                        group,
                                        cluster,
                                        sub,
                                      })
                                    }
                                    className={`w-full text-left rounded-md px-2 py-1 text-[11px] hover:bg-gray-50 ${
                                      selection?.kind === 'subcluster' &&
                                      selection.sub === sub
                                        ? 'bg-primary-50 ring-1 ring-primary-200'
                                        : 'text-gray-700'
                                    }`}
                                  >
                                    {sub.label}
                                    <span className="text-gray-500 ml-1 tabular-nums">
                                      ({sub.count}, {sub.share_pct.toFixed(1)}%)
                                    </span>
                                  </button>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        )
                      })}
                    </div>
                  ) : null}
                </div>
              )
            })
          )}
        </div>

        <div className="p-4 min-h-[240px]">
          <ClusterHierarchyDetail selection={selection} state={state} client={client} />
        </div>
      </div>
    </article>
  )
}

function ClusterHierarchyDetail({
  selection,
  state,
  client,
}: {
  selection: TreeSelection | null
  state: EvaluationMetricClustersState
  client: MetricClustersClient
}) {
  if (!selection) {
    return <p className="text-sm text-gray-500">Select a node in the tree.</p>
  }

  if (selection.kind === 'metric') {
    const { group } = selection
    const policy = state.failure_policies?.[group.metric_id]
    return (
      <div className="space-y-3">
        <h4 className="text-base font-semibold text-gray-900">{group.metric_name}</h4>
        <p className="text-sm text-gray-600">
          {group.flagged_count} flagged calls across {group.clusters.length} cluster
          {group.clusters.length === 1 ? '' : 's'}.
        </p>
        {policy ? (
          <p className="text-xs text-gray-600">
            <span className="font-semibold">Failure policy:</span>{' '}
            {[
              ...(policy.failure_values || []),
              ...(policy.failure_child_names || []),
            ].join(', ') || 'numeric rule'}
          </p>
        ) : null}
        {group.failure_reason ? (
          <p className="text-sm text-gray-700">
            <span className="font-semibold">Why flagged:</span> {group.failure_reason}
          </p>
        ) : null}
      </div>
    )
  }

  if (selection.kind === 'subcluster') {
    const { sub, cluster, group } = selection
    return (
      <div className="space-y-3">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
          Sub-cluster · {group.metric_name}
        </p>
        <h4 className="text-base font-semibold text-gray-900">{sub.label}</h4>
        {sub.id ? (
          <IdRow id={sub.id} label="Sub-cluster ID" />
        ) : null}
        <p className="text-sm text-gray-600 tabular-nums">
          {sub.count} calls · {sub.share_pct.toFixed(1)}% of parent cluster
        </p>
        <p className="text-xs text-gray-500">
          Parent: {cluster.label} ({shortId(cluster.id)})
        </p>
      </div>
    )
  }

  const { cluster, group } = selection
  const exampleHref = client.buildEvidenceHref(cluster.evidence)

  return (
    <div className="space-y-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
        Level-1 cluster · {group.metric_name}
      </p>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h4 className="text-base font-semibold text-gray-900">{cluster.label}</h4>
        <span className={gapBadgeClass()}>
          {cluster.gap_label.replace(/_/g, ' ')}
        </span>
      </div>
      <IdRow id={cluster.id} label="Cluster ID" />
      <p className="text-sm text-gray-600 tabular-nums">
        {cluster.count} calls · {cluster.share_pct.toFixed(1)}% share
      </p>
      {cluster.failure_reason ? (
        <p className="text-sm text-gray-700">
          <span className="font-semibold">Why flagged:</span> {cluster.failure_reason}
        </p>
      ) : null}
      {group.flagged_count > 0 ? (
        <div className="h-2.5 w-full rounded bg-primary-100 overflow-hidden">
          <div
            className="h-full rounded bg-primary-500"
            style={{
              width: `${Math.min(100, (cluster.count / group.flagged_count) * 100).toFixed(1)}%`,
            }}
          />
        </div>
      ) : null}
      {cluster.observation ? (
        <p className="text-sm text-gray-700">{cluster.observation}</p>
      ) : null}
      {cluster.sub_clusters.length ? (
        <div>
          <p className="text-xs font-semibold text-gray-700 mb-1">Sub-clusters</p>
          <ul className="text-xs text-gray-600 space-y-1">
            {cluster.sub_clusters.map((sub) => (
              <li key={sub.id ?? sub.label}>
                {sub.label} — {sub.count} ({sub.share_pct.toFixed(1)}%)
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {cluster.evidence.quote ||
      cluster.evidence.turns?.length ||
      cluster.evidence.conversation_id ? (
        <div className="rounded-md bg-gray-50 border border-gray-100 p-3 space-y-1">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-600">
            Example call
          </p>
          {cluster.evidence.turns?.length
            ? cluster.evidence.turns.map((turn, i) => (
                <p key={i} className="text-xs text-gray-800">
                  <span className="font-semibold text-primary-700">{turn.speaker}:</span>{' '}
                  {turn.text}
                </p>
              ))
            : cluster.evidence.quote ? (
                <p className="text-xs text-gray-800">{cluster.evidence.quote}</p>
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
            <p className="text-[10px] text-gray-500 font-mono">{cluster.evidence.conversation_id}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function IdRow({ id, label }: { id: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 shrink-0">
        {label}
      </span>
      <code className="text-xs font-mono text-gray-800 bg-gray-100 px-2 py-0.5 rounded truncate flex-1">
        {id}
      </code>
      <button
        type="button"
        onClick={() => copyToClipboard(id)}
        className="p-1 rounded hover:bg-gray-100 text-gray-500"
        title="Copy ID"
      >
        <Copy className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
