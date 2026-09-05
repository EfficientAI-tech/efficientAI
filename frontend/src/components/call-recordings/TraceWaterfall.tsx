import { STAGE_COLORS } from '../../lib/callDetailTheme'
import { TurnSignalBadges } from './TraceTurnBadges'
import { formatMs } from './traceUtils'

type ComponentKind = 'stt' | 'llm' | 'tts' | 's2s'

export interface WaterfallRow {
  turnNumber: number
  sttMs?: number | null
  llmMs?: number | null
  ttsMs?: number | null
  s2sMs?: number | null
  totalMs?: number | null
  talkOver?: boolean
  interrupted?: boolean
  incomplete?: boolean
}

const STAGE_META: Record<ComponentKind, { label: string; hint: string }> = {
  stt: { label: 'Listen', hint: 'Speech-to-text' },
  llm: { label: 'Think', hint: 'Language model' },
  tts: { label: 'Speak', hint: 'Text-to-speech' },
  s2s: { label: 'Realtime', hint: 'Speech-to-speech' },
}

function stageValue(row: WaterfallRow, kind: ComponentKind): number | null {
  const value =
    kind === 'stt'
      ? row.sttMs
      : kind === 'llm'
        ? row.llmMs
        : kind === 'tts'
          ? row.ttsMs
          : row.s2sMs
  if (value == null || value <= 0) return null
  return value
}

function activeStages(rows: WaterfallRow[]): ComponentKind[] {
  const kinds: ComponentKind[] = ['stt', 'llm', 'tts']
  if (rows.some((row) => stageValue(row, 's2s') != null)) {
    return ['s2s']
  }
  return kinds.filter((kind) => rows.some((row) => stageValue(row, kind) != null))
}

function columnMaxes(rows: WaterfallRow[], stages: ComponentKind[]): Record<ComponentKind, number> {
  const maxes = { stt: 0, llm: 0, tts: 0, s2s: 0 }
  for (const row of rows) {
    for (const kind of stages) {
      const value = stageValue(row, kind)
      if (value != null) maxes[kind] = Math.max(maxes[kind], value)
    }
  }
  return maxes
}

function StageLegend({ stages }: { stages: ComponentKind[] }) {
  return (
    <div className="flex flex-wrap gap-3">
      {stages.map((kind) => (
        <span key={kind} className="inline-flex items-center gap-1.5 text-xs text-gray-600">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: STAGE_COLORS[kind] }} />
          <span className="font-medium text-gray-800">{STAGE_META[kind].label}</span>
          <span className="text-gray-400">({STAGE_META[kind].hint})</span>
        </span>
      ))}
    </div>
  )
}

function StageCell({
  ms,
  kind,
  columnMax,
}: {
  ms: number | null
  kind: ComponentKind
  columnMax: number
}) {
  if (ms == null) {
    return (
      <td className="px-4 py-3.5 align-top">
        <span className="text-sm text-gray-300">—</span>
      </td>
    )
  }

  const barWidth = columnMax > 0 ? Math.max(10, Math.round((ms / columnMax) * 100)) : 100

  return (
    <td className="px-4 py-3.5 align-top">
      <div className="min-w-[5.5rem] space-y-2">
        <span className="text-sm font-semibold tabular-nums text-gray-900">{formatMs(ms)}</span>
        <div className="h-2 w-full max-w-[9rem] overflow-hidden rounded-full bg-gray-100">
          <div
            className="h-full rounded-full transition-all"
            style={{ width: `${barWidth}%`, backgroundColor: STAGE_COLORS[kind] }}
          />
        </div>
      </div>
    </td>
  )
}

export default function TraceWaterfall({ rows }: { rows: WaterfallRow[] }) {
  if (rows.length === 0) return null

  const stages = activeStages(rows)
  const maxes = columnMaxes(rows, stages)

  return (
    <div className="overflow-hidden rounded-lg border border-primary-200 bg-white">
      <div className="space-y-2 border-b border-gray-100 bg-gray-50/60 px-4 py-3">
        <p className="text-sm font-medium text-gray-900">How long each stage took per turn</p>
        <p className="text-xs text-gray-500">Bars compare turns within the same stage — slower turns have longer bars.</p>
        <StageLegend stages={stages} />
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-white text-left text-[10px] font-semibold uppercase tracking-wider text-gray-400">
              <th className="px-4 py-3 w-28">Turn</th>
              {stages.map((kind) => (
                <th key={kind} className="px-4 py-3">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: STAGE_COLORS[kind] }} />
                    {STAGE_META[kind].label}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((row) => {
              const segments = stages
                .map((kind) => ({ kind, ms: stageValue(row, kind) }))
                .filter((entry) => entry.ms != null)
              if (segments.length === 0) return null

              return (
                <tr key={row.turnNumber} className="hover:bg-gray-50/60">
                  <td className="px-4 py-3.5 align-top">
                    <div className="flex flex-col gap-1.5">
                      <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                        Turn {row.turnNumber}
                      </span>
                      <TurnSignalBadges
                        talkOver={row.talkOver}
                        interrupted={row.interrupted}
                        incomplete={row.incomplete}
                      />
                    </div>
                  </td>
                  {stages.map((kind) => (
                    <StageCell
                      key={kind}
                      kind={kind}
                      ms={stageValue(row, kind)}
                      columnMax={maxes[kind]}
                    />
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
