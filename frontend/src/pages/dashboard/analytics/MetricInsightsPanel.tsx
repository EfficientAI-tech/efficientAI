import { Link } from 'react-router-dom'
import type { MetricVerdict } from './metricVerdict'

export interface MetricImprovement {
  title: string
  body: string
  href?: string
  hrefLabel?: string
}

export default function MetricInsightsPanel({
  summary,
  improvements,
  verdict,
}: {
  summary: string
  improvements: MetricImprovement[]
  verdict: MetricVerdict
}) {
  const verdictStyles =
    verdict.kind === 'relevant'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
      : verdict.kind === 'redundant'
        ? 'border-amber-200 bg-amber-50 text-amber-900'
        : 'border-gray-200 bg-gray-50 text-gray-800'
  const verdictLabel =
    verdict.kind === 'relevant' ? 'Relevant' : verdict.kind === 'redundant' ? 'Redundant' : 'Needs data'

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-gray-900">Summary</h3>
        <p className="mt-1.5 text-sm text-gray-600 leading-relaxed">{summary}</p>
      </section>
      <section className={`rounded-xl border p-4 ${verdictStyles}`}>
        <p className="text-[11px] font-semibold uppercase tracking-wide">{verdictLabel}</p>
        <ul className="mt-1.5 space-y-1 text-sm">
          {verdict.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </section>
      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-gray-900">Suggested improvements</h3>
        {improvements.length === 0 ? (
          <p className="mt-1.5 text-sm text-gray-500">Nothing urgent in this window.</p>
        ) : (
          <ul className="mt-2 space-y-3">
            {improvements.map((item) => (
              <li key={item.title} className="text-sm">
                <p className="font-medium text-gray-900">{item.title}</p>
                <p className="mt-0.5 text-gray-600">{item.body}</p>
                {item.href && (
                  <Link to={item.href} className="mt-1 inline-block text-xs font-medium text-gray-800 underline">
                    {item.hrefLabel ?? 'Open'}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
