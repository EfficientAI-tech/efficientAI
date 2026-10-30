import DeltaChip from './DeltaChip'
import Sparkline from './Sparkline'
import type { DashboardSource } from './timeBuckets'
import type { ScoreDelta, Sentiment } from './metricMath'

export interface MetricAgentRow {
  agentId: string
  agentName: string
  runs: number
  display: string
  failingCount: number
  failingRate: number | null
  delta: ScoreDelta | null
  sentiment: Sentiment
  points: Array<number | null>
}

export default function MetricAgentsTable({
  rows,
  source,
  onOpenAgent,
}: {
  rows: MetricAgentRow[]
  source: DashboardSource
  onOpenAgent: (agentId: string) => void
}) {
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-gray-200 bg-white px-4 py-8 text-sm text-gray-500">
        No agents ran this metric in the selected window.
      </div>
    )
  }
  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-left text-[11px] uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-4 py-2 font-medium">Agent</th>
            <th className="px-4 py-2 font-medium">Runs</th>
            <th className="px-4 py-2 font-medium">Value</th>
            <th className="px-4 py-2 font-medium">Failing</th>
            <th className="px-4 py-2 font-medium">Trend</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.agentId} className="border-t border-gray-100 hover:bg-gray-50">
              <td className="px-4 py-3">
                <button
                  type="button"
                  onClick={() => onOpenAgent(row.agentId)}
                  className="font-medium text-gray-900 hover:underline"
                >
                  {row.agentName}
                </button>
              </td>
              <td className="px-4 py-3 tabular-nums text-gray-600">{row.runs}</td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="tabular-nums font-medium text-gray-900">{row.display}</span>
                  <DeltaChip sentiment={row.sentiment} delta={row.delta} />
                </div>
              </td>
              <td className="px-4 py-3 tabular-nums text-gray-600">
                {row.failingCount}
                {row.failingRate != null ? ` · ${Math.round(row.failingRate * 100)}%` : ''}
              </td>
              <td className="px-4 py-3">
                <Sparkline values={row.points} width={72} height={22} source={source} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
