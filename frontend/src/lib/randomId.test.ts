import { afterEach, describe, expect, it, vi } from 'vitest'
import { randomId } from './randomId'

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

describe('randomId', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses crypto.randomUUID when it exists', () => {
    vi.stubGlobal('crypto', {
      randomUUID: () => '11111111-1111-4111-8111-111111111111',
      getRandomValues: () => {
        throw new Error('fallback should not run')
      },
    })
    expect(randomId()).toBe('11111111-1111-4111-8111-111111111111')
  })

  it('builds a v4 UUID from getRandomValues when randomUUID is missing', () => {
    vi.stubGlobal('crypto', {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(0)
        return bytes
      },
    })
    expect(randomId()).toMatch(UUID_RE)
  })
})
