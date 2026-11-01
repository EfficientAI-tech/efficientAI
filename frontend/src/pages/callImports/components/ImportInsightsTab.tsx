import {
  Activity,
  Database,
  Layers,
  Mic,
  MicOff,
  RefreshCw,
} from 'lucide-react'
import InsightsMetricCard, {
  INSIGHTS_PALETTE,
} from './InsightsMetricCard'
import type { CallImportInsightsResponse } from '../../../types/api'

type KpiTone = 'indigo' | 'emerald' | 'amber' | 'violet' | 'gray'

const KPI_TONE_CLASS: Record<
  KpiTone,
  { card: string; chip: string; icon: string; value: string }
> = {
  indigo: {
    card: 'from-indigo-50 to-white border-indigo-100',
    chip: 'bg-indigo-100 text-indigo-700',
    icon: 'text-indigo-600',
    value: 'text-indigo-900',
  },
  emerald: {
    card: 'from-emerald-50 to-white border-emerald-100',
    chip: 'bg-emerald-100 text-emerald-700',
    icon: 'text-emerald-600',
    value: 'text-emerald-900',
  },
  amber: {
    card: 'from-amber-50 to-white border-amber-100',
    chip: 'bg-amber-100 text-amber-700',
    icon: 'text-amber-600',
    value: 'text-amber-900',
  },
  violet: {
    card: 'from-violet-50 to-white border-violet-100',
    chip: 'bg-violet-100 text-violet-700',
    icon: 'text-violet-600',
    value: 'text-violet-900',
  },
  gray: {
    card: 'from-gray-50 to-white border-gray-200',
    chip: 'bg-gray-100 text-gray-600',
    icon: 'text-gray-500',
    value: 'text-gray-900',
  },
}

function KpiCard({
  Icon,
  label,
  value,
  sub,
  tone = 'gray',
}: {
  Icon: React.ComponentType<{ className?: string }>
  label: string
  value: string | number
  sub?: string | null
  tone?: KpiTone
}) {
  const cls = KPI_TONE_CLASS[tone]
  return (
    <div
      className={`rounded-xl border bg-gradient-to-br ${cls.card} px-3 py-2.5 flex items-start gap-3`}
    >
      <span
        className={`shrink-0 inline-flex items-center justify-center h-8 w-8 rounded-lg ${cls.chip}`}
      >
        <Icon className={`h-4 w-4 ${cls.icon}`} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] uppercase tracking-wider text-gray-500 truncate">
          {label}
        </p>
        <p className={`text-2xl font-semibold leading-tight tabular-nums ${cls.value}`}>
          {value}
        </p>
        {sub ? (
          <p className="text-[10px] text-gray-500 truncate">{sub}</p>
        ) : null}
      </div>
    </div>
  )
}

function TranscriptSourceMix({
  counts,
}: {
  counts: Record<string, number>
}) {
  const entries = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1])
  const total = entries.reduce((s, [, c]) => s + c, 0) || 1
  if (entries.length === 0) return null
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-800 mb-2">
        Transcript source mix
      </h3>
      <div
        className="flex h-6 w-full overflow-hidden rounded-md border border-gray-200"
        role="img"
        aria-label="Transcript source breakdown"
      >
        {entries.map(([source, count], i) => {
          const pct = (count / total) * 100
          const color = INSIGHTS_PALETTE[i % INSIGHTS_PALETTE.length]
          return (
            <div
              key={source}
              style={{ width: `${pct}%`, background: color }}
              title={`${source}: ${count} (${pct.toFixed(1)}%)`}
            />
          )
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-gray-700">
        {entries.map(([source, count], i) => {
          const pct = (count / total) * 100
          const color = INSIGHTS_PALETTE[i % INSIGHTS_PALETTE.length]
          return (
            <div key={source} className="inline-flex items-center gap-1.5">
              <span
                className="h-2.5 w-2.5 rounded-sm"
                style={{ background: color }}
              />
              <span className="font-medium capitalize">{source}</span>
              <span className="text-gray-500 tabular-nums">
                · {count} ({pct.toFixed(0)}%)
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export type ImportInsightsTabProps = {
  insightsLoading: boolean
  insightsData: CallImportInsightsResponse | undefined
}

export default function ImportInsightsTab({
  insightsLoading,
  insightsData,
}: ImportInsightsTabProps) {
  return (
    <div className="bg-white shadow rounded-lg p-6 space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Insights</h2>
        <p className="text-xs text-gray-500 mt-0.5">
          Cross-run signals for this call import. Trend lines show the
          mean of each metric across every evaluation; transcript
          coverage helps you spot rows that still need diarization.
        </p>
      </div>

      {insightsLoading || !insightsData ? (
        <div className="text-center py-12 text-gray-500">
          <RefreshCw className="h-6 w-6 mx-auto mb-2 animate-spin" />
          <p>Loading insights…</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard
              Icon={Database}
              label="Total rows"
              value={insightsData.total_rows}
              tone="indigo"
            />
            <KpiCard
              Icon={Mic}
              label="With transcript"
              value={insightsData.rows_with_transcript}
              sub={
                insightsData.total_rows > 0
                  ? `${Math.round(
                      (insightsData.rows_with_transcript /
                        insightsData.total_rows) *
                        100,
                    )}% coverage`
                  : null
              }
              tone="emerald"
            />
            <KpiCard
              Icon={MicOff}
              label="Missing transcript"
              value={insightsData.rows_without_transcript}
              tone={
                insightsData.rows_without_transcript > 0
                  ? 'amber'
                  : 'gray'
              }
            />
            <KpiCard
              Icon={Activity}
              label="Eval runs"
              value={insightsData.evaluation_count}
              tone="violet"
            />
          </div>

          {Object.keys(insightsData.transcript_source_counts).length >
            0 && (
            <TranscriptSourceMix
              counts={insightsData.transcript_source_counts}
            />
          )}

          {insightsData.metrics.length === 0 ? (
            <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50/40 px-6 py-10 text-center">
              <Layers className="h-6 w-6 text-gray-400 mx-auto mb-2" />
              <p className="text-sm text-gray-600">
                Run at least one evaluation to populate metric trends.
              </p>
            </div>
          ) : (
            <div>
              <h3 className="text-sm font-semibold text-gray-800 mb-3">
                Metric trends
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {insightsData.metrics.map((m) => (
                  <InsightsMetricCard key={m.metric_id} metric={m} />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
