export interface CallTurn {
  speaker: 'agent' | 'human'
  text: string
  start: number
  end: number
  toolCall?: { name: string; failed: boolean }
  ragCall?: { query: string; failed: boolean }
}

export interface CallLike {
  id: string
  agentId: string
  source: 'simulation' | 'live'
  startedAt: string
  durationSeconds: number
  turns: CallTurn[]
  endedEarly: boolean
  closingQuality: number
}

export interface PerCallMetrics {
  durationSeconds: number
  closingQuality: number
  endedEarly: boolean
  earlyEnding: number
  silenceAvgSeconds: number
  silenceMaxSeconds: number
  toolCallFailures: number
  ragCallFailures: number
  talkRatio: number | null
}

export function computeCallMetrics(call: CallLike): PerCallMetrics {
  const gaps: number[] = []
  const ordered = [...call.turns].sort((a, b) => a.start - b.start)
  for (let i = 1; i < ordered.length; i += 1) {
    const gap = ordered[i].start - ordered[i - 1].end
    if (gap >= 0) gaps.push(gap)
  }
  const agentTurns = ordered.filter((turn) => turn.speaker === 'agent').length
  const humanTurns = ordered.filter((turn) => turn.speaker === 'human').length
  const toolCallFailures = ordered.filter((turn) => turn.toolCall?.failed).length
  const ragCallFailures = ordered.filter((turn) => turn.ragCall?.failed).length
  const silenceAvg = gaps.length ? gaps.reduce((sum, gap) => sum + gap, 0) / gaps.length : 0
  return {
    durationSeconds: call.durationSeconds,
    closingQuality: call.closingQuality,
    endedEarly: call.endedEarly,
    earlyEnding: call.endedEarly ? 1 : 0,
    silenceAvgSeconds: silenceAvg,
    silenceMaxSeconds: gaps.length ? Math.max(...gaps) : 0,
    toolCallFailures,
    ragCallFailures,
    talkRatio: humanTurns === 0 ? null : agentTurns / humanTurns,
  }
}