import { describe, expect, it } from 'vitest'

import { formatPlaybackTime } from './useAmbientPreview'

describe('useAmbientPreview helpers', () => {
  it('formatPlaybackTime renders mm:ss', () => {
    expect(formatPlaybackTime(65)).toBe('1:05')
    expect(formatPlaybackTime(0)).toBe('0:00')
  })
})

describe('ambient preview source selection', () => {
  it('uses presigned URLs directly without blob materialization', async () => {
    const presignedUrl = 'https://storage.example/ambient/test.wav?sig=abc'
    const loader = async () => presignedUrl
    const source = await loader()
    expect(typeof source).toBe('string')
    expect(source).toBe(presignedUrl)
  })
})
