import type { ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type ComponentKind = 'stt' | 'llm' | 'tts' | 's2s'

const SLICE_COLORS: Record<ComponentKind, string> = {
  stt: '#d4d4d8',
  llm: '#a16207',
  tts: '#a1a1aa',
  s2s: '#71717a',
}

const BAR_FILL_DEFAULT = '#a1a1aa'
const BAR_FILL_PEAK = '#854d0e'

const STAGE_LABELS: Record<ComponentKind, string> = {
  stt: 'STT',
  llm: 'LLM',
  tts: 'TTS',
  s2s: 'S2S',
}

const CHART_GRID = '#f3f4f6'
const CHART_AXIS = '#9ca3af'

export interface LayerTurnInput {
  sttMs?: number | null
  llmMs?: number | null
  ttsMs?: number | null
  s2sMs?: number | null
}

function accumulateStageSums(rows: LayerTurnInput[]): Record<ComponentKind, number> {
  const sums: Record<ComponentKind, number> = { stt: 0, llm: 0, tts: 0, s2s: 0 }
  for (const row of rows) {
    if (row.s2sMs != null && row.s2sMs > 0) {
      sums.s2s += row.s2sMs
      continue
    }
    if (row.sttMs != null && row.sttMs > 0) sums.stt += row.sttMs
    if (row.llmMs != null && row.llmMs > 0) sums.llm += row.llmMs
    if (row.ttsMs != null && row.ttsMs > 0) sums.tts += row.ttsMs
  }
  return sums
}

export function LayerResponseDonut({ rows }: { rows: LayerTurnInput[] }) {
  const sums = accumulateStageSums(rows)

  const slices = (['stt', 'llm', 'tts', 's2s'] as const)
    .map((kind) => (sums[kind] > 0 ? { name: STAGE_LABELS[kind], kind, value: sums[kind] } : null))
    .filter(Boolean) as Array<{ name: string; kind: ComponentKind; value: number }>

  const total = slices.reduce((s, x) => s + x.value, 0)
  if (total <= 0) return null

  return (
    <div className="rounded-lg border border-primary-300 bg-white p-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">Layer response</p>
      <p className="mt-0.5 text-[11px] text-gray-400">Cumulative stage latency across all turns</p>
      <div className="relative mt-3 h-44">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={slices}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={52}
              outerRadius={72}
              paddingAngle={2}
              stroke="#fff"
              strokeWidth={2}
            >
              {slices.map((slice) => (
                <Cell key={slice.kind} fill={SLICE_COLORS[slice.kind]} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value: number, name: string) => [
                `${Math.round(value)}ms (${Math.round((value / total) * 100)}%)`,
                name,
              ]}
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-bold tabular-nums text-gray-900">
            {total >= 1000 ? `${(total / 1000).toFixed(1)}s` : Math.round(total)}
          </span>
          <span className="text-[10px] text-gray-400">{total >= 1000 ? 'stage time' : 'ms stage time'}</span>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap justify-center gap-2 text-[11px] text-gray-600">
        {slices.map((slice) => (
          <span
            key={slice.kind}
            className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 ${
              slice.kind === 'llm'
                ? 'border-primary-300 bg-primary-50/60'
                : 'border-gray-200 bg-gray-50/80'
            }`}
          >
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: SLICE_COLORS[slice.kind] }} />
            {slice.name}{' '}
            <span className="font-semibold tabular-nums text-gray-800">{Math.round(slice.value)}ms</span>
          </span>
        ))}
      </div>
    </div>
  )
}

export interface TurnBarRow {
  turn: string
  total: number
  talkOver?: boolean
  interrupted?: boolean
  incomplete?: boolean
}

function turnSignalLines(row: TurnBarRow): string[] {
  const lines: string[] = []
  if (row.talkOver) lines.push('Talk-over')
  if (row.interrupted) lines.push('Interrupted')
  if (row.incomplete) lines.push('Incomplete data')
  return lines
}

function TurnBarTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ payload?: TurnBarRow }>
}) {
  if (!active || !payload?.[0]?.payload) return null
  const row = payload[0].payload
  const signals = turnSignalLines(row)
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-gray-900">
        {row.turn}: {Math.round(row.total)}ms
      </p>
      {signals.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-gray-600">
          {signals.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function TurnTotalsBar({ rows }: { rows: TurnBarRow[] }) {
  if (rows.length === 0) return null

  const peak = Math.max(...rows.map((r) => r.total))

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">Response by turn</p>
      <p className="mt-0.5 text-[11px] text-gray-400">End-to-end agent response (sut) per turn</p>
      <div className="mt-3 h-44">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} vertical={false} />
            <XAxis dataKey="turn" tick={{ fontSize: 11, fill: CHART_AXIS }} axisLine={false} tickLine={false} />
            <YAxis
              tick={{ fontSize: 11, fill: CHART_AXIS }}
              axisLine={false}
              tickLine={false}
              width={44}
              tickFormatter={(v) => `${v}`}
            />
            <Tooltip content={<TurnBarTooltip />} />
            <Bar dataKey="total" radius={[3, 3, 0, 0]} maxBarSize={40}>
              {rows.map((entry) => (
                <Cell
                  key={entry.turn}
                  fill={entry.total === peak && peak > 0 ? BAR_FILL_PEAK : BAR_FILL_DEFAULT}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p>}
      </div>
      {children}
    </section>
  )
}

export { Section as TraceSection }
