import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import CallHits from './CallHits'
import { CHART_PALETTE } from './dashboardSection'
import { agentDashboardStats, agentName } from './dashboardSelectors'
import { useDashboardNav } from './dashboardNav'
import { useDashboardFilters } from './useDashboardFilters'
import SectionShell from './SectionShell'

export default function AgentDashboardSection() {
  const nav = useDashboardNav()
  const filters = useDashboardFilters()
  const agentId = filters.agentId
  if (!agentId) {
    return (
      <SectionShell section="agent" current="Agent" onBack={nav.openOverview}>
        <p className="text-sm text-gray-500">Select an agent from a chart or the table.</p>
      </SectionShell>
    )
  }
  const stats = agentDashboardStats(nav.calls, agentId)

  return (
    <SectionShell section="agent" current={agentName(agentId)} onBack={nav.openOverview}>
      <h1 className="text-2xl font-semibold text-gray-900">{agentName(agentId)}</h1>
      <p className="text-sm text-gray-500">
        {stats.callCount} calls · {stats.metricsAssigned} metrics · {stats.toolCount} tools · {stats.scenarioCount} scenarios
      </p>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="mb-2 text-sm font-medium text-gray-900">Usage over time</p>
          <div className="h-48">
            <ResponsiveContainer>
              <LineChart data={stats.usageOverTime.map((row) => ({ ...row, label: row.day.slice(5) }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Line type="monotone" dataKey="value" stroke="#6366f1" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="mb-2 text-sm font-medium text-gray-900">
            Metrics · most used {stats.mostUsedMetric?.name ?? '—'}
          </p>
          <div className="h-48">
            <ResponsiveContainer>
              <BarChart data={stats.metricCounts}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                <XAxis dataKey="name" tick={{ fontSize: 9 }} interval={0} angle={-20} textAnchor="end" height={60} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="count" fill={CHART_PALETTE[0]} cursor="pointer" onClick={(entry) => {
                  const id = (entry as { id?: string }).id
                  if (id) nav.openMetric(id)
                }} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="mb-2 text-sm font-medium text-gray-900">Use cases</p>
          <div className="h-48">
            <ResponsiveContainer>
              <BarChart data={stats.tools} layout="vertical">
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="count" fill={CHART_PALETTE[1]} cursor="pointer" onClick={(entry) => {
                  const name = (entry as { name?: string }).name
                  if (name) nav.openTool(name)
                }} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="mb-2 text-sm font-medium text-gray-900">
            Scenarios · {stats.scenarioMetricCount} scenario-specific metrics
          </p>
          <div className="h-48">
            <ResponsiveContainer>
              <BarChart data={stats.scenarios.mostFrequent.filter((item) => item.agentId === agentId || item.count > 0)}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                <XAxis dataKey="name" tick={{ fontSize: 9 }} interval={0} angle={-20} textAnchor="end" height={70} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="count" fill={CHART_PALETTE[2]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>
      <div>
        <p className="mb-2 text-sm font-medium text-gray-900">Calls</p>
        <CallHits calls={stats.calls} currency={nav.currency} onOpenCall={nav.openCall} extra={(call) => `${call.usage.tokens.toLocaleString()} tok`} />
      </div>
    </SectionShell>
  )
}
