import { describe, expect, it } from 'vitest'
import { aggregateCalls, computeCallMetrics, globalValuesFromCall } from './callMetrics'
import type { CallLike } from './callMetrics'

function call(partial: Partial<CallLike> & Pick<CallLike, 'turns'>): CallLike {
  return {
    id: 'c1',
    agentId: 'a1',
    source: 'simulation',
    startedAt: '2026-10-01T00:00:00.000Z',
    durationSeconds: 40,
    endedEarly: false,
    closingQuality: 4,
    ...partial,
  }
}

describe('computeCallMetrics', () => {
  it('measures silence gaps, talk ratio, and tool/RAG failures', () => {
    const metrics = computeCallMetrics(
      call({
        durationSeconds: 30,
        closingQuality: 2,
        endedEarly: true,
        turns: [
          { speaker: 'human', text: 'Hi', start: 0, end: 2 },
          { speaker: 'agent', text: 'Hello', start: 5, end: 8, toolCall: { name: 'lookup', failed: true } },
          { speaker: 'human', text: 'Help', start: 10, end: 12, ragCall: { query: 'policy', failed: true } },
          { speaker: 'agent', text: 'Sure', start: 18, end: 20 },
        ],
      }),
    )
    expect(metrics.silenceGaps).toEqual([3, 2, 6])
    expect(metrics.silenceAvgSeconds).toBeCloseTo(11 / 3)
    expect(metrics.silenceMaxSeconds).toBe(6)
    expect(metrics.silenceMinSeconds).toBe(2)
    expect(metrics.agentTurns).toBe(2)
    expect(metrics.humanTurns).toBe(2)
    expect(metrics.talkRatio).toBe(1)
    expect(metrics.toolCallFailures).toBe(1)
    expect(metrics.ragCallFailures).toBe(1)
    expect(metrics.earlyEnding).toBe(1)
    expect(globalValuesFromCall(metrics).avg_duration).toBe(30)
  })

  it('returns a null talk ratio when the caller never speaks', () => {
    const metrics = computeCallMetrics(
      call({
        turns: [{ speaker: 'agent', text: 'Hello?', start: 0, end: 2 }],
      }),
    )
    expect(metrics.talkRatio).toBeNull()
    expect(metrics.silenceGaps).toEqual([])
  })
})

describe('aggregateCalls', () => {
  const calls: CallLike[] = [
    call({
      id: 'a',
      durationSeconds: 20,
      closingQuality: 5,
      endedEarly: false,
      turns: [
        { speaker: 'human', text: 'a', start: 0, end: 1 },
        { speaker: 'agent', text: 'b', start: 2, end: 3 },
      ],
    }),
    call({
      id: 'b',
      durationSeconds: 40,
      closingQuality: 3,
      endedEarly: true,
      turns: [
        { speaker: 'human', text: 'a', start: 0, end: 1 },
        { speaker: 'agent', text: 'b', start: 4, end: 5 },
        { speaker: 'agent', text: 'c', start: 6, end: 7 },
      ],
    }),
  ]

  it('averages duration and rates, and sums count metrics', () => {
    const duration = aggregateCalls(calls, 'avg_duration')
    expect(duration.count).toBe(2)
    expect(duration.avg).toBe(30)
    expect(duration.min).toBe(20)
    expect(duration.max).toBe(40)

    const early = aggregateCalls(calls, 'early_ending', { op: 'eq', value: 1 })
    expect(early.avg).toBe(1)
    expect(early.failingCount).toBe(1)
    expect(early.count).toBe(2)

    const total = aggregateCalls(calls, 'total_calls')
    expect(total.sum).toBe(1)
    expect(total.avg).toBe(1)
  })
})
