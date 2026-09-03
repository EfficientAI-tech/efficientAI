import { describe, expect, it } from 'vitest'
import { buildVapiCallTimeline } from './callTimelineUtils'

describe('buildVapiCallTimeline', () => {
  it('orders call ended after pipeline events and uses real timestamps', () => {
    const events = buildVapiCallTimeline({
      status: 'ended',
      type: 'webCall',
      createdAt: '2026-09-02T18:24:30.000Z',
      startedAt: '2026-09-02T18:24:31.000Z',
      endedAt: '2026-09-02T18:25:03.000Z',
      endedReason: 'customer-ended-call',
      artifact: {
        messages: [
          { role: 'system', message: 'System prompt', secondsFromStart: 0 },
          { role: 'bot', message: 'Hello.', secondsFromStart: 1.62 },
          { role: 'user', message: 'Hi', secondsFromStart: 8.46, duration: 1200 },
        ],
        performanceMetrics: {
          turnLatencies: [
            {
              turnNumber: 1,
              transcriberLatency: 571,
              endpointingLatency: 304,
              modelLatency: 359,
              voiceLatency: 350,
              turnLatency: 1287,
            },
            {
              turnNumber: 2,
              transcriberLatency: 516,
              endpointingLatency: 300,
              modelLatency: 509,
              voiceLatency: 354,
              turnLatency: 1397,
            },
          ],
        },
      },
    })

    const endedIdx = events.findIndex((e) => e.title === 'Call ended')
    const lastPipelineIdx = events.map((e) => e.title).lastIndexOf('Turn 2 pipeline complete')
    expect(endedIdx).toBeGreaterThan(lastPipelineIdx)

    const ended = events[endedIdx]
    expect(ended.offsetMs).toBeGreaterThanOrEqual(32000)

    expect(events.some((e) => e.title === 'Turn 1 — transcriber')).toBe(true)
    expect(events.some((e) => e.detail?.includes('$'))).toBe(false)
    expect(events.some((e) => e.detail?.startsWith('https://'))).toBe(false)
  })

  it('ignores null entries in artifact messages', () => {
    const events = buildVapiCallTimeline({
      status: 'ended',
      startedAt: '2026-09-02T18:24:31.000Z',
      endedAt: '2026-09-02T18:25:03.000Z',
      artifact: {
        messages: [
          null,
          { role: 'user', message: 'Hi', secondsFromStart: 1 },
          { role: 'bot', message: 'Hello', secondsFromStart: 2 },
        ],
      },
    })

    expect(events.some((e) => e.title === 'User spoke')).toBe(true)
    expect(events.some((e) => e.title === 'Call ended')).toBe(true)
  })
})
