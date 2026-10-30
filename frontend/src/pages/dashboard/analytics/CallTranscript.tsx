import { globalMetricById, isGlobalMetricId } from './globalMetrics'
import type { MockCall } from './mockCalls'

export default function CallTranscript({
  call,
  metricId,
}: {
  call: MockCall
  metricId: string
}) {
  const global = globalMetricById(metricId)
  const localScore = call.metric_scores[metricId]
  const highlightTurns = new Set(localScore?.evidenceTurnIndexes ?? [])
  const lastIndex = call.turns.length - 1
  const highlightEarly = Boolean(global && (global.id === 'early_ending' || global.id === 'closing_quality') && (call.endedEarly || (localScore?.failed ?? call.closingQuality < 3)))

  return (
    <div className="space-y-2">
      {global?.id === 'early_ending' && call.endedEarly && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900">
          Call ended early ({call.endedReason ?? 'unknown reason'}). Last turns are highlighted.
        </div>
      )}
      {global?.id === 'closing_quality' && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Closing quality {call.closingQuality.toFixed(1)} / 5. The wrap-up turns are highlighted.
        </div>
      )}
      {call.turns.map((turn, index) => {
        const gap = index > 0 ? turn.start - call.turns[index - 1].end : 0
        const silenceHot =
          global &&
          (global.id === 'silence_duration' || global.id === 'longest_pause') &&
          gap > (global.id === 'longest_pause' ? 6 : 2.5)
        const toolHot = global?.id === 'tool_call_failures' && Boolean(turn.toolCall?.failed)
        const ragHot = global?.id === 'rag_call_failures' && Boolean(turn.ragCall?.failed)
        const localHot = highlightTurns.has(index)
        const closingHot = highlightEarly && index >= lastIndex - 1
        const hot = toolHot || ragHot || localHot || closingHot
        const side = turn.speaker === 'human' ? 'justify-start' : 'justify-end'
        const bubble =
          turn.speaker === 'human'
            ? 'bg-gray-100 text-gray-900'
            : 'bg-indigo-50 text-indigo-950'
        return (
          <div key={`${turn.start}-${index}`}>
            {index > 0 && (
              <div
                className={`my-1 text-center text-[10px] ${
                  silenceHot ? 'font-semibold text-rose-600' : 'text-gray-400'
                }`}
              >
                {silenceHot ? 'Long pause' : 'gap'} {gap.toFixed(1)}s
              </div>
            )}
            <div className={`flex ${side}`}>
              <div
                className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm leading-relaxed ${bubble} ${
                  hot ? 'ring-2 ring-rose-400' : ''
                }`}
              >
                <p className="text-[10px] uppercase tracking-wide opacity-60">{turn.speaker}</p>
                <p>{turn.text}</p>
                {turn.toolCall && (
                  <p className={`mt-1 text-[11px] ${turn.toolCall.failed ? 'text-rose-700' : 'text-gray-500'}`}>
                    Tool {turn.toolCall.name}
                    {turn.toolCall.failed ? ' failed' : ' ok'}
                  </p>
                )}
                {turn.ragCall && (
                  <p className={`mt-1 text-[11px] ${turn.ragCall.failed ? 'text-rose-700' : 'text-gray-500'}`}>
                    RAG “{turn.ragCall.query}”
                    {turn.ragCall.failed ? ' failed' : ' ok'}
                  </p>
                )}
                {localHot && localScore?.rationale && (
                  <p className="mt-1 text-[11px] text-rose-700">{localScore.rationale}</p>
                )}
              </div>
            </div>
          </div>
        )
      })}
      {isGlobalMetricId(metricId) && global?.id === 'avg_duration' && (
        <p className="text-xs text-gray-500 pt-2">Duration {call.durationSeconds}s.</p>
      )}
    </div>
  )
}
