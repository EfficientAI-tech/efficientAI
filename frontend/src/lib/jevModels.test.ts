import { describe, expect, it } from 'vitest'
import { extraJevModelsForProvider, isJevModel } from './jevModels'

describe('isJevModel', () => {
  it('accepts TypeSafe Jev, Together Tev1, and OpenRouter Jev slugs', () => {
    expect(isJevModel('typesafe', 'jev-latest')).toBe(true)
    expect(isJevModel('typesafe', 'jev-1.13.0')).toBe(true)
    expect(isJevModel('together', 'together/Tev1-4B-experimental')).toBe(true)
    expect(isJevModel('openrouter', 'typesafe/jev-latest')).toBe(true)
    expect(isJevModel('openrouter', 'typesafe/jev-1.13.0')).toBe(true)
    expect(isJevModel(null, 'typesafe/jev-1.13.0')).toBe(true)
  })

  it('rejects ordinary chat models', () => {
    expect(isJevModel('openai', 'gpt-4o')).toBe(false)
    expect(isJevModel('together', 'zai-org/GLM-4.6')).toBe(false)
    expect(isJevModel('together', '')).toBe(false)
  })

  it('offers TypeSafe slugs on TypeSafe and OpenRouter', () => {
    expect(extraJevModelsForProvider('openrouter')).toContain('typesafe/jev-1.13.0')
    expect(extraJevModelsForProvider('typesafe')).toContain('typesafe/jev-1.13.0')
    expect(extraJevModelsForProvider('together')).toEqual([])
  })
})
