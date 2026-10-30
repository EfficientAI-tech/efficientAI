import { useMemo } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import HorizontalStackedBar from './charts/HorizontalStackedBar'
import { agentChartSeries, CHART_PALETTE } from './dashboardSection'
import { modelStats, modelUsageByKind } from './dashboardSelectors'
import { useDashboardNav } from './dashboardNav'
import { MOCK_MODELS, modelPriceHistory, type ModelKind } from './mockUsage'
import SectionShell from './SectionShell'

const KINDS: Array<{ id: ModelKind; label: string }> = [
  { id: 'stt', label: 'STT models' },
  { id: 'tts', label: 'TTS models' },
  { id: 'llm', label: 'LLM models' },
  { id: 's2s', label: 'S2S models' },
]

export default function UsageSection() {
  const nav = useDashboardNav()
  const byKind = modelUsageByKind(nav.calls)
  const stats = modelStats(nav.calls)
  const future = useMemo(() => {
    const from = nav.calls[0] ? new Date(nav.calls[0].startedAt) : new Date(Date.now() - 7 * 86400000)
    const to = new Date()
    to.setDate(to.getDate() + 30)
    const earliest = nav.calls.reduce((min, call) => Math.min(min, new Date(call.startedAt).getTime()), from.getTime())
    const start = new Date(earliest)
    const minuteModels = MOCK_MODELS.filter((model) => model.unit === 'per_minute')
    const tokenModels = MOCK_MODELS.filter((model) => model.unit === 'per_1m_tokens')
    const build = (models: typeof MOCK_MODELS) => {
      const histories = models.map((model) => ({ model, rows: modelPriceHistory(model.id, start, to) }))
      const days = histories[0]?.rows.map((row) => row.day) ?? []
      return days.map((day, index) => {
        const point: Record<string, string | number> = { day: day.slice(5) }
        for (const item of histories) point[item.model.id] = item.rows[index]?.price ?? 0
        return point
      })
    }
    return { minute: build(minuteModels), token: build(tokenModels), minuteModels, tokenModels }
  }, [nav.calls])

  return (
    <SectionShell section="usage" current="Usage" onBack={nav.openOverview}>
      <h1 className="text-2xl font-semibold text-gray-900">Usage</h1>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {KINDS.map((kind) => {
          const rows = byKind[kind.id].map((row) => {
            const point: Record<string, string | number> = { name: row.name, modelId: row.modelId }
            for (const agent of row.byAgent) point[agent.agentId] = agent.usage
            return point
          })
          return (
            <section key={kind.id} className="rounded-xl border border-gray-200 bg-white p-4">
              <p className="mb-2 text-sm font-medium text-gray-900">{kind.label}</p>
              <HorizontalStackedBar
                rows={rows}
                series={agentChartSeries()}
                onBarClick={(name) => {
                  const match = byKind[kind.id].find((row) => row.name === name)
                  if (match) nav.openModel(match.modelId)
                }}
              />
            </section>
          )
        })}
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <PriceChart title="Price / minute going forward" data={future.minute} models={future.minuteModels} />
        <PriceChart title="Price / 1M tokens going forward" data={future.token} models={future.tokenModels} />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Most used" value={stats.mostUsed?.name ?? '—'} onClick={() => stats.mostUsed && nav.openModel(stats.mostUsed.modelId)} />
        <StatCard label="Least used" value={stats.leastUsed?.name ?? '—'} onClick={() => stats.leastUsed && nav.openModel(stats.leastUsed.modelId)} />
        <StatCard
          label="Lowest latency avg"
          value={stats.lowestLatency ? `${Math.round(stats.lowestLatency.avgLatencyMs)} ms` : '—'}
          onClick={() => stats.lowestLatency && nav.openModel(stats.lowestLatency.modelId)}
        />
        <StatCard
          label="Highest cost"
          value={stats.highestCost?.name ?? '—'}
          onClick={() => stats.highestCost && nav.openModel(stats.highestCost.modelId)}
        />
      </div>
    </SectionShell>
  )
}

function PriceChart({
  title,
  data,
  models,
}: {
  title: string
  data: Array<Record<string, string | number>>
  models: Array<{ id: string; name: string }>
}) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4">
      <p className="mb-2 text-sm font-medium text-gray-900">{title}</p>
      <div className="h-56">
        <ResponsiveContainer>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
            <XAxis dataKey="day" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            {models.map((model, index) => (
              <Line key={model.id} type="monotone" dataKey={model.id} name={model.name} stroke={CHART_PALETTE[index % CHART_PALETTE.length]} dot={false} strokeWidth={1.5} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}

function StatCard({ label, value, onClick }: { label: string; value: string; onClick?: () => void }) {
  return (
    <button type="button" onClick={onClick} className="rounded-xl border border-gray-200 bg-white p-3 text-left hover:border-gray-300">
      <p className="text-[11px] uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-gray-900">{value}</p>
    </button>
  )
}

