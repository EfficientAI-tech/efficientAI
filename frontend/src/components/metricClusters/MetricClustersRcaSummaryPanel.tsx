import { type ReactNode } from 'react'
import type { MetricClustersRcaSummary } from './types'

function RcaExecutiveBar({ pct, scaleMax }: { pct: number; scaleMax: number }) {
  const width =
    scaleMax > 0 ? Math.min(100, Math.round((pct / scaleMax) * 100)) : 0
  return (
    <div className="h-2.5 rounded-sm bg-[#e7ddd1] border border-[#d7cfc2] overflow-hidden w-full max-w-full">
      <div
        className="h-full bg-[#c7725e] rounded-sm transition-all"
        style={{ width: `${width}%` }}
      />
    </div>
  )
}

function RcaExecutiveInterpretation({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border border-rose-100 bg-rose-50/70 px-3 py-2.5 mt-3">
      <p className="text-[10px] font-bold uppercase tracking-wide text-rose-800 mb-1">
        Executive interpretation
      </p>
      <p className="text-xs text-gray-800 leading-relaxed">{children}</p>
    </div>
  )
}

export default function MetricClustersRcaSummaryPanel({
  summary,
}: {
  summary: MetricClustersRcaSummary
}) {
  const topPattern = summary.repeated_patterns[0]
  const topHotspot = summary.metric_hotspots[0]
  const maxPatternShare = Math.max(
    ...summary.repeated_patterns.map((r) => r.evidence_share_pct),
    1,
  )
  const maxHotspotRate = Math.max(
    ...summary.metric_hotspots.map((r) => r.metric_rate_pct),
    1,
  )
  const totalFlagged =
    summary.total_flagged_instances ??
    summary.metric_hotspots.reduce((sum, r) => sum + r.flagged_calls, 0)

  return (
    <article className="rounded-lg border border-gray-200 bg-[#faf7f2]/80 p-4 space-y-6">
      <div>
        <h4 className="text-base font-semibold text-gray-900">
          Executive summary — evaluation set
        </h4>
        <p className="text-xs text-gray-600 mt-1">
          Top metrics by clustered failure patterns and overall flagged rate across{' '}
          {summary.analysed_calls.toLocaleString()} analysed calls.
        </p>
      </div>

      {summary.repeated_patterns.length ? (
        <section className="space-y-2">
          <div className="border-b border-gray-200 pb-2 space-y-1">
            <h5 className="text-sm font-semibold text-gray-900">
              Repeated failure patterns
            </h5>
            <p className="text-[10px] text-gray-500 uppercase tracking-wide">
              Base: {summary.total_clusters} RCA clusters from{' '}
              {summary.total_clustered_instances.toLocaleString()} clustered instances ·{' '}
              {totalFlagged.toLocaleString()} flagged metric-call instances
            </p>
          </div>
          <div className="overflow-x-auto rounded-md border border-gray-100 bg-white max-w-full mx-auto">
            <table className="w-full table-fixed text-xs">
              <colgroup>
                <col className="w-[41%]" />
                <col className="w-[12%]" />
                <col className="w-[29%]" />
                <col className="w-[18%]" />
              </colgroup>
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-gray-500 border-b border-gray-100">
                  <th className="px-2 py-2 font-semibold text-left">Finding</th>
                  <th className="px-2 py-2 font-semibold text-center">
                    Evidence share
                  </th>
                  <th className="px-2 py-2 font-semibold text-center">Distribution</th>
                  <th className="px-2 py-2 font-semibold text-center">
                    Evidence calls
                  </th>
                </tr>
              </thead>
              <tbody>
                {summary.repeated_patterns.map((row) => (
                  <tr
                    key={row.metric_id}
                    className="border-b border-gray-50 align-top last:border-0"
                  >
                    <td className="px-2 py-2.5 text-left">
                      <p className="font-bold text-gray-900 uppercase tracking-tight text-[11px]">
                        {row.metric_name}
                      </p>
                      <p className="text-[10px] text-gray-500 mt-1 leading-snug break-words">
                        Top RCA patterns: {row.top_rca_patterns}
                      </p>
                    </td>
                    <td className="px-2 py-2.5 text-center tabular-nums font-semibold text-gray-900 align-top">
                      {row.evidence_share_pct.toFixed(1)}%
                    </td>
                    <td className="px-2 py-2.5 align-middle">
                      <RcaExecutiveBar
                        pct={row.evidence_share_pct}
                        scaleMax={maxPatternShare}
                      />
                    </td>
                    <td className="px-2 py-2.5 text-center tabular-nums text-gray-900 align-top">
                      <p className="font-semibold text-[11px]">
                        {row.evidence_calls.toLocaleString()}
                      </p>
                      <p className="text-[10px] text-gray-500 font-medium mt-0.5">
                        {row.evidence_share_pct.toFixed(1)}%
                      </p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {topPattern ? (
            <RcaExecutiveInterpretation>
              These rows group repeated RCA failure patterns by metric so the same
              metric is not repeated across multiple rows. The largest group is{' '}
              <span className="font-semibold">{topPattern.metric_name}</span>; focus
              remediation there first using the example calls in each cluster below.
            </RcaExecutiveInterpretation>
          ) : null}
        </section>
      ) : null}

      {summary.metric_hotspots.length ? (
        <section className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-gray-200 pb-2">
            <h5 className="text-sm font-semibold text-gray-900">Metric hotspots</h5>
            <p className="text-[10px] text-gray-500 uppercase tracking-wide">
              Base: selected metric flags across{' '}
              {summary.analysed_calls.toLocaleString()} analysed calls
            </p>
          </div>
          <div className="overflow-x-auto rounded-md border border-gray-100 bg-white">
            <table className="w-full min-w-[520px] text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-gray-500 border-b border-gray-100">
                  <th className="px-3 py-2 font-semibold w-[42%]">Finding</th>
                  <th className="px-3 py-2 font-semibold text-right w-[14%]">
                    Metric rate
                  </th>
                  <th className="px-3 py-2 font-semibold w-[26%]">Distribution</th>
                  <th className="px-3 py-2 font-semibold text-right w-[18%]">
                    Flagged calls
                  </th>
                </tr>
              </thead>
              <tbody>
                {summary.metric_hotspots.map((row) => (
                  <tr
                    key={row.metric_id}
                    className="border-b border-gray-50 align-top last:border-0"
                  >
                    <td className="px-3 py-2.5">
                      <p className="font-bold text-gray-900 uppercase tracking-tight text-[11px]">
                        {row.metric_name}
                      </p>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums font-semibold text-gray-900">
                      {row.metric_rate_pct.toFixed(2)}%
                    </td>
                    <td className="px-3 py-2.5">
                      <RcaExecutiveBar
                        pct={row.metric_rate_pct}
                        scaleMax={maxHotspotRate}
                      />
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums font-semibold text-gray-900">
                      {row.flagged_calls.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {topHotspot ? (
            <RcaExecutiveInterpretation>
              Across {summary.analysed_calls.toLocaleString()} analysed calls,{' '}
              <span className="font-semibold">{topHotspot.metric_name}</span> has the
              highest metric rate at {topHotspot.metric_rate_pct.toFixed(2)}%.
            </RcaExecutiveInterpretation>
          ) : null}
        </section>
      ) : null}

      {summary.prompt_areas.length ? (
        <section className="space-y-2 pt-2 border-t border-gray-200">
          <h5 className="text-sm font-semibold text-gray-900">RCA data summary</h5>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-600">
            Prompt areas to inspect
          </p>
          <table className="w-full text-xs border border-gray-100 rounded-md overflow-hidden bg-white">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Area</th>
                <th className="text-right px-3 py-2 font-medium">%</th>
              </tr>
            </thead>
            <tbody>
              {summary.prompt_areas.map((row) => (
                <tr key={row.label} className="border-t border-gray-100">
                  <td className="px-3 py-2 text-gray-800">{row.label}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                    {row.share_pct.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      <section className="pt-4 mt-2 border-t border-gray-200 space-y-1">
        <h5 className="text-sm font-semibold text-gray-900">Appendix: What is a cluster?</h5>
        <p className="text-xs text-gray-600 leading-relaxed">
          A cluster groups flagged calls that share the same underlying failure theme within
          a quality metric. Each cluster is labeled with an RCA pattern name and an
          engineering gap type (such as MISSING, LOGIC_GAP, UNDERSPEC, or
          EXISTS_NO_TRIGGER). Evidence share is the percentage of all clustered failure
          instances attributed to that metric&apos;s patterns; evidence calls is the raw
          count of those instances.
        </p>
      </section>
    </article>
  )
}
