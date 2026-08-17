import { describe, expect, it } from 'vitest'
import {
  buildEnvelopeFromSegments,
  buildSegmentActivityBuckets,
  formatPlaybackTime,
  isUserSpeakerLabel,
} from './audioWaveform'

describe('audioWaveform helpers', () => {
  it('formats playback time', () => {
    expect(formatPlaybackTime(65)).toBe('1:05')
    expect(formatPlaybackTime(0)).toBe('0:00')
  })

  it('detects user speaker labels', () => {
    expect(isUserSpeakerLabel('user')).toBe(true)
    expect(isUserSpeakerLabel('Speaker 1')).toBe(true)
    expect(isUserSpeakerLabel('assistant')).toBe(false)
  })

  it('builds segment activity buckets', () => {
    const { user, agent } = buildSegmentActivityBuckets(
      [
        { speaker: 'user', start: 0, end: 1 },
        { speaker: 'assistant', start: 2, end: 3 },
      ],
      4,
      8,
      isUserSpeakerLabel,
    )

    expect(user.slice(0, 2).some((value) => value > 0)).toBe(true)
    expect(agent.slice(4, 6).some((value) => value > 0)).toBe(true)
    expect(user.slice(4, 6).every((value) => value === 0)).toBe(true)
  })

  it('builds envelope from transcript segments', () => {
    const envelope = buildEnvelopeFromSegments(
      [
        { speaker: 'user', start: 0, end: 1 },
        { speaker: 'assistant', start: 2, end: 3 },
      ],
      4,
      8,
    )

    expect(envelope.duration).toBe(4)
    expect(envelope.user.length).toBe(8)
    expect(envelope.agent.length).toBe(8)
  })
})
