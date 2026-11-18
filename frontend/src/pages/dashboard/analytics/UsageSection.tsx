import { useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import HorizontalStackedBar from './charts/HorizontalStackedBar'
import { agentChartSeries, CHART_PALETTE } from './dashboardSection'
import { modelStats, modelUsageByKind } from './dashboardSelectors'
import { useDashboardNav } from './dashboardNav'
import { MOCK_MODELS, modelPriceHistory, type ModelKind } from './mockUsage'
import SectionShell from './SectionShell'

const VIEWS: Array<{ id: ModelKind | 'minute' | 'tokens'; label: string }> = [
  { id: 'stt', label: 'STT models' },
  { id: 'tts', label: 'TTS models' },
  { id: 'llm', label: 'LLM models' },
  { id: 's2s', label: 'S2S models' },
  { id: 'minute', label: 'Price / minute' },
  { id: 'tokens', label: 'Price / 1M tokens' },
]

export default function UsageSection() {
  const nav = useDashboardNav()
  const [view, setView] = useState<(typeof VIEWS)[number]['id']>('stt')
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

  const active = VIEWS.find((item) => item.id === view) ?? VIEWS[0]
  const modelRows = view === 'minute' || view === 'tokens'
    ? []
    : byKind[view].map((row) => {
      const point: Record<string, string | number> = { name: row.name, modelId: row.modelId }
      for (const agent of row.byAgent) point[agent.agentId] = agent.usage
      return point
    })

  return (
    <SectionShell section="usage" current="Usage" onBack={nav.openOverview}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold text-gray-900">Usage</h1>
        <div className="flex flex-wrap gap-2">
          {VIEWS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setView(item.id)}
              className={`rounded-lg border px-4 py-2 text-sm font-semibold shadow-sm ${view === item.id
                  ? 'border-gray-900 bg-gray-900 text-white'
                  : 'border-gray-300 bg-white text-gray-800 hover:border-gray-500 hover:bg-gray-50'
                }`}
            >
              {item.label}
            </button>
          ))}
        </div>
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
      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <p className="mb-3 text-sm font-semibold text-gray-900">{active.label}</p>
        {view === 'minute' || view === 'tokens' ? (
          <PriceChart
            data={view === 'minute' ? future.minute : future.token}
            models={view === 'minute' ? future.minuteModels : future.tokenModels}
          />
        ) : (
          <HorizontalStackedBar
            rows={modelRows}
            series={agentChartSeries()}
            onBarClick={(name) => {
              const match = byKind[view].find((row) => row.name === name)
              if (match) nav.openModel(match.modelId)
            }}
          />
        )}
      </section>
    </SectionShell>
  )
}

function PriceChart({
  data,
  models,
}: {
  data: Array<Record<string, string | number>>
  models: Array<{ id: string; name: string }>
}) {
  return (
    <div className="h-72">
      <ResponsiveContainer>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
          <XAxis dataKey="day" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip content={<PriceTooltip models={models} />} />
          {models.map((model, index) => (
            <Line key={model.id} type="monotone" dataKey={model.id} name={model.name} stroke={CHART_PALETTE[index % CHART_PALETTE.length]} dot={false} strokeWidth={2} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function PriceTooltip({
  active,
  payload,
  label,
  models,
}: {
  active?: boolean
  payload?: Array<{ dataKey?: string | number; value?: number | string; color?: string }>
  label?: string | number
  models: Array<{ id: string; name: string }>
}) {
  if (!active || !payload?.length) return null
  const names = new Map(models.map((model) => [model.id, model.name]))
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-semibold text-gray-900">{label}</p>
      {payload.map((item) => (
        <p key={String(item.dataKey)} className="font-medium" style={{ color: item.color ?? '#374151' }}>
          {names.get(String(item.dataKey)) ?? item.dataKey}: {typeof item.value === 'number' ? item.value.toFixed(4) : item.value}
        </p>
      ))}
    </div>
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

