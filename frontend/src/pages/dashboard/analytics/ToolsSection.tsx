import { useMemo, useState } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import HorizontalStackedBar from './charts/HorizontalStackedBar'
import InsightTrendChart from './charts/InsightTrendChart'
import { agentChartSeries } from './dashboardSection'
import { integrationUseStats, integrationUsageOverTimeMulti } from './dashboardSelectors'
import { useDashboardNav } from './dashboardNav'
import { MOCK_INTEGRATIONS } from './mockCatalog'
import SectionShell from './SectionShell'

export default function ToolsSection() {
  const nav = useDashboardNav()
  const stats = integrationUseStats(nav.calls)
  const [visible, setVisible] = useState<string[]>(MOCK_INTEGRATIONS.map((item) => item.id))
  const rows = useMemo(
    () =>
      stats.rows
        .filter((row) => visible.includes(row.id ?? row.name))
        .map((row) => {
          const point: Record<string, string | number> = { name: row.name }
          for (const agent of row.byAgent) point[agent.agentId] = agent.count
          return point
        }),
    [stats.rows, visible],
  )
  const trend = integrationUsageOverTimeMulti(nav.calls, visible).map((row) => ({
    label: String(row.day).slice(5),
    ...row,
  }))
  const donut = stats.rows.filter((row) => visible.includes(row.id ?? row.name))

  return (
    <SectionShell section="tools" current="Tools" onBack={nav.openOverview}>
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Tools</h1>
        <p className="mt-1 text-sm text-gray-500">
          Products the agents connect to — Postgres, Notion, Slack, and the rest. Use cases live under Tool calls.
        </p>
      </div>
      <div className="flex flex-wrap gap-1">
        {MOCK_INTEGRATIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() =>
              setVisible((current) =>
                current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id],
              )
            }
            className={`rounded-full px-2 py-0.5 text-[11px] ${
              visible.includes(item.id) ? 'text-white' : 'bg-gray-100 text-gray-600'
            }`}
            style={visible.includes(item.id) ? { backgroundColor: item.color } : undefined}
          >
            {item.name}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="mb-2 text-sm font-medium text-gray-900">Share of tool traffic</p>
          <div className="h-48">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={donut} dataKey="count" nameKey="name" innerRadius={36} outerRadius={68}>
                  {donut.map((row) => (
                    <Cell
                      key={row.id ?? row.name}
                      fill={row.color ?? '#6366f1'}
                      cursor="pointer"
                      onClick={() => nav.openTool(row.id ?? row.name)}
                    />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="mt-2 space-y-1 text-xs text-gray-600">
            {donut.map((row) => (
              <li key={row.id ?? row.name}>
                <button
                  type="button"
                  className="flex w-full items-center gap-1.5 hover:underline"
                  onClick={() => nav.openTool(row.id ?? row.name)}
                >
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: row.color }} />
                  {row.name}
                  <span className="ml-auto tabular-nums">{row.count}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="mb-2 text-sm font-medium text-gray-900">Usage over time</p>
          <InsightTrendChart
            points={trend}
            kind="area"
            series={donut.map((row) => ({
              key: row.id ?? row.name,
              label: row.name,
              color: row.color,
            }))}
            height={220}
          />
        </section>
      </div>
      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <p className="mb-2 text-sm font-medium text-gray-900">By agent</p>
        <HorizontalStackedBar rows={rows} series={agentChartSeries()} onBarClick={(name) => nav.openTool(name)} />
      </section>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <button
          type="button"
          className="rounded-xl border border-gray-200 bg-white p-3 text-left hover:border-gray-300"
          onClick={() => stats.maxInCall && nav.openCall(stats.maxInCall.callId)}
        >
          <p className="text-[11px] uppercase tracking-wide text-gray-400">Most tools in a call</p>
          <p className="mt-1 text-sm font-semibold text-gray-900">
            {stats.maxInCall ? `${stats.maxInCall.agentName} · ${stats.maxInCall.count}` : '—'}
          </p>
        </button>
        <button
          type="button"
          className="rounded-xl border border-gray-200 bg-white p-3 text-left hover:border-gray-300"
          onClick={() => stats.mostUsed && nav.openTool(stats.mostUsed.id ?? stats.mostUsed.name)}
        >
          <p className="text-[11px] uppercase tracking-wide text-gray-400">Most used tool</p>
          <p className="mt-1 text-sm font-semibold text-gray-900">{stats.mostUsed?.name ?? '—'}</p>
        </button>
        <button
          type="button"
          className="rounded-xl border border-gray-200 bg-white p-3 text-left hover:border-gray-300"
          onClick={() => stats.leastUsed && nav.openTool(stats.leastUsed.id ?? stats.leastUsed.name)}
        >
          <p className="text-[11px] uppercase tracking-wide text-gray-400">Least used tool</p>
          <p className="mt-1 text-sm font-semibold text-gray-900">{stats.leastUsed?.name ?? '—'}</p>
        </button>
        <div className="rounded-xl border border-gray-200 bg-white p-3">
          <p className="text-[11px] uppercase tracking-wide text-gray-400">Calls with no tools</p>
          <p className="mt-1 text-sm font-semibold text-gray-900">{stats.noToolCalls.toLocaleString()}</p>
        </div>
      </div>
    </SectionShell>
  )
}
