import { ArrowRight } from 'lucide-react'
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

const STAGE_LABELS: Record<ComponentKind, string> = {
  stt: 'STT',
  llm: 'LLM',
  tts: 'TTS',
  s2s: 'S2S',
}

function formatMsLocal(value?: number | null): string {
  return formatMs(value)
}

function turnSegments(row: WaterfallRow): Array<{ kind: ComponentKind; ms: number }> {
  const parts: Array<{ kind: ComponentKind; ms: number }> = []
  if (row.s2sMs != null && row.s2sMs > 0) parts.push({ kind: 's2s', ms: row.s2sMs })
  else {
    if (row.sttMs != null && row.sttMs > 0) parts.push({ kind: 'stt', ms: row.sttMs })
    if (row.llmMs != null && row.llmMs > 0) parts.push({ kind: 'llm', ms: row.llmMs })
    if (row.ttsMs != null && row.ttsMs > 0) parts.push({ kind: 'tts', ms: row.ttsMs })
  }
  return parts
}

function StageNode({ kind, ms }: { kind: ComponentKind; ms: number }) {
  const highlight = kind === 'llm'
  return (
    <div
      className={`flex min-w-[4.5rem] flex-col rounded-lg border px-2.5 py-2 ${
        highlight
          ? 'border-primary-300 bg-primary-50/50'
          : 'border-gray-200 bg-white'
      }`}
      title={`${STAGE_LABELS[kind]} ${formatMsLocal(ms)}`}
    >
      <span className={`text-[10px] font-semibold uppercase tracking-wide ${highlight ? 'text-primary-800' : 'text-gray-400'}`}>
        {STAGE_LABELS[kind]}
      </span>
      <span className={`mt-0.5 text-sm font-semibold tabular-nums ${highlight ? 'text-primary-900' : 'text-gray-800'}`}>
        {formatMsLocal(ms)}
      </span>
    </div>
  )
}

export default function TraceWaterfall({ rows }: { rows: WaterfallRow[] }) {
  if (rows.length === 0) return null

  const turnTotal = (row: WaterfallRow) => {
    const segments = turnSegments(row)
    return row.totalMs ?? (segments.length > 0 ? segments.reduce((s, p) => s + p.ms, 0) : 0)
  }

  const maxTotal = Math.max(...rows.map(turnTotal), 1)

  return (
    <div className="overflow-hidden rounded-lg border border-primary-200 bg-white">
      <div className="border-b border-gray-100 bg-gray-50/60 px-4 py-2.5">
        <p className="text-xs text-gray-500">
          Per-turn pipeline flow — stages run left to right in order
        </p>
      </div>

      <div className="divide-y divide-gray-100">
        {rows.map((row) => {
          const segments = turnSegments(row)
          const total = turnTotal(row)
          const widthPct = total > 0 ? Math.max((total / maxTotal) * 100, 12) : 12

          return (
            <div key={row.turnNumber} className="px-4 py-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                    Turn {row.turnNumber}
                  </span>
                  <TurnSignalBadges
                    talkOver={row.talkOver}
                    interrupted={row.interrupted}
                    incomplete={row.incomplete}
                  />
                </div>
                <span className="text-sm font-semibold tabular-nums text-gray-900">
                  {formatMsLocal(total)}
                  <span className="ml-1 text-xs font-normal text-gray-400">total</span>
                </span>
              </div>

              {segments.length === 0 ? (
                <p className="text-xs text-gray-400">No stage timing</p>
              ) : (
                <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
                  {segments.map((seg, idx) => (
                    <div key={seg.kind} className="flex items-center gap-1.5 sm:gap-2">
                      {idx > 0 && <ArrowRight className="h-3.5 w-3.5 shrink-0 text-gray-300" aria-hidden />}
                      <StageNode kind={seg.kind} ms={seg.ms} />
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-3 h-1 overflow-hidden rounded-full bg-gray-100">
                <div
                  className="h-full rounded-full bg-gray-300"
                  style={{ width: `${widthPct}%` }}
                  title={`${formatMsLocal(total)} of ${formatMsLocal(maxTotal)} max`}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
