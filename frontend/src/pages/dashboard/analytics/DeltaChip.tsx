import { sentimentClasses, type Sentiment } from './metricMath'
import type { ScoreDelta } from './metricMath'

export default function DeltaChip({
  sentiment,
  delta,
}: {
  sentiment: Sentiment
  delta: ScoreDelta | null
}) {
  if (!delta) return null
  const colors = sentimentClasses(sentiment)
  const arrow =
    delta.direction === 'up' ? '↑' : delta.direction === 'down' ? '↓' : '→'
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${colors.text} ${colors.bg} ${colors.border}`}
    >
      <span aria-hidden>{arrow}</span>
      {delta.direction === 'flat' ? 'Flat' : delta.display}
    </span>
  )
}
