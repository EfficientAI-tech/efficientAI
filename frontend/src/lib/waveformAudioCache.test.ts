import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({
  apiClient: {
    getCallRecordingAudioBuffer: vi.fn(),
    getObservabilityCallAudioBuffer: vi.fn(),
    getEvaluatorResultAudioBuffer: vi.fn(),
  },
}))

import {
  __resetWaveformAudioCacheForTests,
  clearCallRecordingAudioCache,
  getOrCreatePlaybackBlobUrl,
  getPlaybackBlobUrl,
  playbackKeyForCall,
  releasePlaybackBlobUrl,
  retainPlaybackBlobUrl,
  setCachedWaveform,
} from './waveformAudioCache'

function makeBuffer(label: string): ArrayBuffer {
  const bytes = new TextEncoder().encode(label)
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)
}

describe('waveformAudioCache blob lifecycle', () => {
  beforeEach(() => {
    __resetWaveformAudioCacheForTests()
  })

  it('creates and reuses blob URLs for the same key', () => {
    const key = playbackKeyForCall('123456', false)
    const buffer = makeBuffer('audio')
    const first = getOrCreatePlaybackBlobUrl(key, buffer)
    const second = getOrCreatePlaybackBlobUrl(key, buffer)
    expect(first).toBe(second)
    expect(getPlaybackBlobUrl(key)).toBe(first)
  })

  it('does not revoke blob URLs while they are retained', () => {
    const key = playbackKeyForCall('123456', false)
    const url = getOrCreatePlaybackBlobUrl(key, makeBuffer('audio'))
    retainPlaybackBlobUrl(key)

    clearCallRecordingAudioCache('123456')

    expect(getPlaybackBlobUrl(key)).toBe(url)

    releasePlaybackBlobUrl(key)
    expect(getPlaybackBlobUrl(key)).toBeNull()
  })

  it('keeps retained blob URLs when waveform cache is evicted', () => {
    const key = playbackKeyForCall('123456', false)
    const url = getOrCreatePlaybackBlobUrl(key, makeBuffer('audio'))
    retainPlaybackBlobUrl(key)
    setCachedWaveform('123456', false, {
      tracks: [],
      duration: 10,
    })

    for (let i = 0; i < 12; i++) {
      setCachedWaveform(`${100000 + i}`, false, { tracks: [], duration: 1 })
    }

    expect(getPlaybackBlobUrl(key)).toBe(url)
    releasePlaybackBlobUrl(key)
  })
})
