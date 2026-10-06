import type { ReactNode } from 'react'

export type ClassificationScoreView = {
  answers?: Record<string, unknown>
  error?: unknown
}

export type ClassificationHeadlines = {
  yesNo: string | null
  category: string | null
  level: string | null
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return null
}

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function fmtPct(probability: number): string {
  return `${Math.round(Math.max(0, Math.min(1, probability)) * 100)}%`
}

export function humanizeClassificationLabel(raw: string): string {
  const t = raw.trim()
  if (!t) return t
  if (t === 'other') return 'Other'
  return t
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

type ProbEntry = { key: string; label: string; prob: number }

function sortedProbEntries(
  probabilities: unknown,
  legend?: Record<string, unknown> | null,
  limit?: number,
): ProbEntry[] {
  const probs = asRecord(probabilities)
  if (!probs) return []
  const sorted = Object.entries(probs)
    .map(([key, value]) => {
      const prob = asNumber(value)
      if (prob === null) return null
      const legendLabel = legend ? legend[key] ?? legend[String(Number(key))] : null
      return {
        key,
        label: legendLabel != null ? String(legendLabel) : humanizeClassificationLabel(key),
        prob,
      }
    })
    .filter((x): x is ProbEntry => x !== null)
    .sort((a, b) => b.prob - a.prob)
  return limit != null ? sorted.slice(0, limit) : sorted
}

/** Primary Yes/No, category, and level labels for compact table cells. */
export function getClassificationHeadlines(
  score: ClassificationScoreView,
): ClassificationHeadlines {
  const empty: ClassificationHeadlines = {
    yesNo: null,
    category: null,
    level: null,
  }
  if (score.error) return empty
  const answers = score.answers
  if (!answers || typeof answers !== 'object') return empty

  let yesNo: string | null = null
  const noul = asRecord(answers.noul)
  const noulP = noul ? asNumber(noul.noul) : null
  if (noulP !== null) {
    yesNo = noulP >= 0.5 ? 'Yes' : 'No'
  }

  let category: string | null = null
  const choice = asRecord(answers.choice)
  if (choice?.choice != null) {
    category = humanizeClassificationLabel(String(choice.choice))
  } else if (choice) {
    const top = sortedProbEntries(choice.probabilities, null, 1)[0]
    if (top) category = top.label
  }

  let level: string | null = null
  const scoreAns = asRecord(answers.score)
  if (scoreAns) {
    const legend = asRecord(scoreAns.legend)
    const top = sortedProbEntries(scoreAns.probabilities, legend, 1)[0]
    if (top) {
      level = top.label
    } else {
      const scoreVal = asNumber(scoreAns.score)
      if (scoreVal !== null) level = scoreVal.toFixed(2)
    }
  }

  return { yesNo, category, level }
}

export function formatClassificationScoreTooltip(
  score: ClassificationScoreView,
): string | undefined {
  if (score.error) return String(score.error)
  const { yesNo, category, level } = getClassificationHeadlines(score)
  const parts: string[] = []
  if (yesNo) parts.push(`Yes/No: ${yesNo}`)
  if (category) parts.push(`Category: ${category}`)
  if (level) parts.push(`Level: ${level}`)
  if (parts.length) {
    parts.push('Click row for probability breakdown')
  }
  return parts.length ? parts.join(' · ') : undefined
}

function ProbBar({ probability }: { probability: number }) {
  const pct = Math.max(0, Math.min(100, probability * 100))
  return (
    <div className="h-1.5 flex-1 min-w-[48px] max-w-[120px] rounded-full bg-gray-100 overflow-hidden">
      <div
        className="h-full rounded-full bg-indigo-500/80"
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
        {title}
      </div>
      {children}
    </div>
  )
}

function SummaryLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-xs leading-snug">
      <div className="text-[10px] font-medium uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div
        className="font-medium text-gray-900 break-words whitespace-normal"
        title={value}
      >
        {value}
      </div>
    </div>
  )
}

/** Compact table cell: main Yes/No, category, and level only. */
export function ClassificationScoreSummary({
  score,
}: {
  score: ClassificationScoreView
}) {
  const tooltip = formatClassificationScoreTooltip(score)

  if (score.error) {
    return (
      <span className="text-amber-700 text-xs" title={tooltip}>
        Could not classify
      </span>
    )
  }

  const { yesNo, category, level } = getClassificationHeadlines(score)
  if (!yesNo && !category && !level) {
    return <span className="text-gray-300">-</span>
  }

  return (
    <div
      className="space-y-1.5 py-0.5 min-w-[9rem] max-w-[16rem] w-max"
      title={tooltip}
    >
      {yesNo && <SummaryLine label="Yes/No" value={yesNo} />}
      {category && <SummaryLine label="Category" value={category} />}
      {level && <SummaryLine label="Level" value={level} />}
    </div>
  )
}

function NoulDetailBlock({ noul }: { noul: Record<string, unknown> }) {
  const p = asNumber(noul.noul)
  if (p === null) return null
  const yes = Math.max(0, Math.min(1, p))
  const answer = yes >= 0.5 ? 'Yes' : 'No'

  return (
    <Section title="Yes / no">
      <div className="text-sm font-semibold text-gray-900">{answer}</div>
      <div className="flex items-center gap-2 text-[11px] text-gray-600">
        <span className="w-8 shrink-0">Yes</span>
        <ProbBar probability={yes} />
        <span className="tabular-nums w-9 text-right shrink-0">{fmtPct(yes)}</span>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-gray-600">
        <span className="w-8 shrink-0">No</span>
        <ProbBar probability={1 - yes} />
        <span className="tabular-nums w-9 text-right shrink-0">
          {fmtPct(1 - yes)}
        </span>
      </div>
    </Section>
  )
}

function ChoiceDetailBlock({ choice }: { choice: Record<string, unknown> }) {
  const selected = choice.choice != null ? String(choice.choice) : null
  const conf = asNumber(choice.confidence)
  const entries = sortedProbEntries(choice.probabilities, null)
  if (!selected && entries.length === 0) return null

  return (
    <Section title="Category">
      {selected && (
        <div className="flex items-baseline gap-1.5 flex-wrap">
          <span className="text-sm font-semibold text-gray-900">
            {humanizeClassificationLabel(selected)}
          </span>
          {conf !== null && (
            <span className="text-xs text-gray-500">{fmtPct(conf)} confidence</span>
          )}
        </div>
      )}
      {entries.length > 0 && (
        <ul className="space-y-1.5 mt-1">
          {entries.map((e) => (
            <li key={e.key} className="flex items-center gap-2 text-[11px]">
              <span
                className={`truncate min-w-0 flex-1 max-w-[140px] ${
                  selected && e.key === selected
                    ? 'font-medium text-gray-900'
                    : 'text-gray-600'
                }`}
                title={e.label}
              >
                {e.label}
              </span>
              <ProbBar probability={e.prob} />
              <span className="text-gray-500 tabular-nums w-9 text-right shrink-0">
                {fmtPct(e.prob)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function ScoreDetailBlock({ scoreAns }: { scoreAns: Record<string, unknown> }) {
  const legend = asRecord(scoreAns.legend)
  const conf = asNumber(scoreAns.confidence)
  const entries = sortedProbEntries(scoreAns.probabilities, legend)
  const scoreVal = asNumber(scoreAns.score)

  if (entries.length === 0 && scoreVal === null) return null

  const top = entries[0]
  const headline = top ? top.label : scoreVal !== null ? scoreVal.toFixed(2) : '—'

  return (
    <Section title="Level">
      <div className="flex items-baseline gap-1.5 flex-wrap">
        <span className="text-sm font-semibold text-gray-900">{headline}</span>
        {conf !== null && (
          <span className="text-xs text-gray-500">{fmtPct(conf)} confidence</span>
        )}
        {scoreVal !== null && (
          <span className="text-[10px] text-gray-400">
            Score index {scoreVal.toFixed(2)}
          </span>
        )}
      </div>
      {entries.length > 0 && (
        <ul className="space-y-1.5 mt-1">
          {entries.map((e) => (
            <li key={e.key} className="flex items-center gap-2 text-[11px]">
              <span className="truncate min-w-0 flex-1 max-w-[140px] text-gray-600" title={e.label}>
                {e.label}
              </span>
              <ProbBar probability={e.prob} />
              <span className="text-gray-500 tabular-nums w-9 text-right shrink-0">
                {fmtPct(e.prob)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

/** Row detail panel: headlines plus full probability breakdown. */
export function ClassificationScoreDetail({
  score,
}: {
  score: ClassificationScoreView
}) {
  const answers = score.answers

  if (score.error) {
    return (
      <span className="text-amber-700 text-xs">
        Could not classify
      </span>
    )
  }

  if (!answers || typeof answers !== 'object') {
    return <span className="text-gray-400 text-sm">—</span>
  }

  const noul = asRecord(answers.noul)
  const choice = asRecord(answers.choice)
  const scoreAns = asRecord(answers.score)

  const hasNoul = noul && asNumber(noul.noul) !== null
  const hasChoice =
    choice &&
    (choice.choice != null ||
      sortedProbEntries(choice.probabilities, null, 1).length > 0)
  const hasScore =
    scoreAns &&
    (asNumber(scoreAns.score) !== null ||
      sortedProbEntries(scoreAns.probabilities, asRecord(scoreAns.legend), 1)
        .length > 0)

  if (!hasNoul && !hasChoice && !hasScore) {
    return <span className="text-gray-400 text-sm">—</span>
  }

  return (
    <div className="space-y-3 pt-1">
      {hasNoul && noul && <NoulDetailBlock noul={noul} />}
      {hasChoice && choice && <ChoiceDetailBlock choice={choice} />}
      {hasScore && scoreAns && <ScoreDetailBlock scoreAns={scoreAns} />}
    </div>
  )
}

/** @deprecated Use ClassificationScoreSummary in tables. */
export function ClassificationScoreCell({
  score,
}: {
  score: ClassificationScoreView
}) {
  return <ClassificationScoreSummary score={score} />
}
