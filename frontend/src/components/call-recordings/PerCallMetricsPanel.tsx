import type { ReactNode } from 'react'
import { formatGlobalValue, globalMetricById, STRIP_METRIC_IDS } from './perCallGlobalMetrics'
import type { EvaluatorPerCallMetricsView } from './evaluatorPerCallMetrics'
import { perCallGlobalFailed, perCallGlobalValue } from './evaluatorPerCallMetrics'

export default function PerCallMetricsPanel({ view }: { view: EvaluatorPerCallMetricsView }) {
  const globalDefs = STRIP_METRIC_IDS.map((id) => globalMetricById(id)).filter(
    (metric): metric is NonNullable<typeof metric> => Boolean(metric?.clickable),
  )

  return (
    <div className="max-w-lg space-y-4">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-600">Run metrics</h3>
      <MetricSection title="Global">
        {globalDefs.map((metric) => (
          <div key={metric.id}>
            <MetricRow
              label={metric.name}
              value={formatGlobalValue(metric, perCallGlobalValue(view.computed, metric.id))}
              failed={perCallGlobalFailed(view.computed, metric.id)}
            />
            {metric.subMetricIds?.map((subId) => {
              const sub = globalMetricById(subId)
              if (!sub) return null
              return (
                <MetricRow
                  key={sub.id}
                  label={sub.name}
                  value={formatGlobalValue(sub, perCallGlobalValue(view.computed, sub.id))}
                  failed={perCallGlobalFailed(view.computed, sub.id)}
                  nested
                />
              )
            })}
          </div>
        ))}
      </MetricSection>
      {view.quality.length > 0 ? (
        <MetricSection title="Local quality">
          {view.quality.map((row) => (
            <MetricRow key={row.metricId} label={row.label} value={row.value} failed={row.failed} />
          ))}
        </MetricSection>
      ) : null}
      {view.outcome.length > 0 ? (
        <MetricSection title="Call outcome">
          {view.outcome.map((row) => (
            <MetricRow key={row.metricId} label={row.label} value={row.value} failed={row.failed} />
          ))}
        </MetricSection>
      ) : null}
      {view.insights.length > 0 ? (
        <MetricSection title="Insights">
          {view.insights.map((row) => (
            <MetricRow key={row.metricId} label={row.label} value={row.value} failed={row.failed} />
          ))}
        </MetricSection>
      ) : null}
    </div>
  )
}

function MetricSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-gray-100 bg-gray-50/70 px-3 py-2.5">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</p>
      <div className="space-y-1.5">{children}</div>
    </section>
  )
}

function MetricRow({
  label,
  value,
  failed,
  nested,
}: {
  label: string
  value: string
  failed?: boolean
  nested?: boolean
}) {
  return (
    <div
      className={`flex justify-between gap-3 rounded-md px-2 py-1.5 text-sm leading-snug ${nested ? 'ml-2' : ''
        } ${failed ? 'text-rose-700' : 'text-gray-800'}`}
    >
      <span className="min-w-0 shrink text-gray-600">{label}</span>
      <span
        className={`shrink-0 text-right tabular-nums font-semibold ${failed ? 'text-rose-700' : 'text-gray-900'}`}
      >
        {value}
      </span>
    </div>
  )
}