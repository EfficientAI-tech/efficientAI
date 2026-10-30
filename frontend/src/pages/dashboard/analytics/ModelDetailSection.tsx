import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from 'recharts'
import CallHits from './CallHits'
import { callsForModel, modelUsageOverTime } from './dashboardSelectors'
import { useDashboardNav } from './dashboardNav'
import { modelById } from './mockUsage'
import { useDashboardFilters } from './useDashboardFilters'
import SectionShell from './SectionShell'

export default function ModelDetailSection() {
  const nav = useDashboardNav()
  const filters = useDashboardFilters()
  const model = modelById(filters.modelId ?? '')
  const series = modelUsageOverTime(nav.calls, filters.modelId ?? '')
  const hits = callsForModel(nav.calls, filters.modelId ?? '')

  return (
    <SectionShell section="model" current={model?.name ?? 'Model'} onBack={nav.openUsage}>
      <h1 className="text-2xl font-semibold text-gray-900">{model?.name ?? 'Model'}</h1>
      <p className="text-sm text-gray-500">{model?.kind.toUpperCase()} · {model?.unit === 'per_1m_tokens' ? '$ / 1M tokens' : '$ / minute'}</p>
      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <p className="mb-2 text-sm font-medium text-gray-900">Usage over time</p>
        <div className="h-56">
          <ResponsiveContainer>
            <LineChart data={series.map((row) => ({ ...row, label: row.day.slice(5) }))}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Line type="monotone" dataKey="value" stroke="#6366f1" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>
      <div>
        <p className="mb-2 text-sm font-medium text-gray-900">Calls · most tokens first</p>
        <CallHits
          calls={hits}
          currency={nav.currency}
          onOpenCall={nav.openCall}
          extra={(call) => `${call.usage.tokens.toLocaleString()} tok`}
        />
      </div>
    </SectionShell>
  )
}
