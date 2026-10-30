import { Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid, Legend } from 'recharts'
import { AGENT_COLORS, CHART_PALETTE } from './dashboardSection'
import { toolCallsOverTime, toolsPerCallByAgent, toolUsageRows } from './dashboardSelectors'
import { useDashboardNav } from './dashboardNav'
import { MOCK_AGENTS, USE_CASE_INTEGRATION, integrationById } from './mockCatalog'
import SectionShell from './SectionShell'

export default function ToolCallsSection() {
  const nav = useDashboardNav()
  const overTime = toolCallsOverTime(nav.calls)
  const pie = toolsPerCallByAgent(nav.calls)
  const tools = toolUsageRows(nav.calls).filter((row) => row.count > 0)

  return (
    <SectionShell section="tool-calls" current="Tool calls" onBack={nav.openOverview}>
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Tool calls</h1>
        <p className="mt-1 text-sm text-gray-500">
          Use cases the agents invoke — lookup order, create ticket, refund — not the products themselves.
        </p>
      </div>
      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <p className="mb-2 text-sm font-medium text-gray-900">Usage over time by agent</p>
        <div className="h-64">
          <ResponsiveContainer>
            <LineChart data={overTime.map((row) => ({ ...row, label: String(row.day).slice(5) }))}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Legend />
              {MOCK_AGENTS.map((agent) => (
                <Line
                  key={agent.id}
                  type="monotone"
                  dataKey={agent.id}
                  name={agent.name}
                  stroke={AGENT_COLORS[agent.id] ?? '#6366f1'}
                  dot={false}
                  strokeWidth={2}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="mb-2 text-sm font-medium text-gray-900">Use cases per call by agent</p>
          <div className="h-48">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={pie} dataKey="avg" nameKey="agentName" innerRadius={32} outerRadius={64}>
                  {pie.map((row, index) => (
                    <Cell
                      key={row.agentId}
                      fill={CHART_PALETTE[index % CHART_PALETTE.length]}
                      cursor="pointer"
                      onClick={() => nav.openAgent(row.agentId)}
                    />
                  ))}
                </Pie>
                <Tooltip formatter={(value) => (typeof value === 'number' ? value.toFixed(2) : value)} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="mt-2 space-y-1 text-xs text-gray-600">
            {pie.map((row, index) => (
              <li key={row.agentId}>
                <button type="button" className="flex w-full items-center gap-1.5 hover:underline" onClick={() => nav.openAgent(row.agentId)}>
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: CHART_PALETTE[index % CHART_PALETTE.length] }} />
                  {row.agentName}
                  <span className="ml-auto tabular-nums">{row.avg.toFixed(2)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="mb-2 text-sm font-medium text-gray-900">Use cases</p>
          <ul className="space-y-1 text-sm">
            {tools.map((row, index) => {
              const integration = integrationById(USE_CASE_INTEGRATION[row.name as keyof typeof USE_CASE_INTEGRATION] ?? '')
              return (
                <li key={row.name}>
                  <button
                    type="button"
                    onClick={() => nav.openTool(row.name)}
                    className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 hover:bg-gray-50"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: CHART_PALETTE[index % CHART_PALETTE.length] }} />
                      <span className="truncate font-medium text-gray-800">{row.name}</span>
                      {integration && (
                        <span className="truncate text-[11px] text-gray-400" style={{ color: integration.color }}>
                          {integration.name}
                        </span>
                      )}
                    </span>
                    <span className="tabular-nums text-gray-500">{row.count}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      </div>
    </SectionShell>
  )
}
