import { describe, expect, it } from 'vitest'
import {
  isClassificationCapableModel,
  isClassificationMetric,
  isStandardJudgeModel,
  mergeClassificationOverrides,
  resolveLLMModelsForCredential,
  seedClassificationLLM,
} from './llmModelOptions'
import type { AIProvider } from '../types/api'

function makeCredential(overrides: Partial<AIProvider> = {}): AIProvider {
  return {
    id: 'cred-1',
    organization_id: 'org-1',
    provider: 'custom',
    api_key: 'managed',
    is_active: true,
    is_default: true,
    routing_mode: 'gateway',
    ...overrides,
  } as AIProvider
}

describe('resolveLLMModelsForCredential', () => {
  it('returns enabled_models when catalog is empty for custom provider', () => {
    const credential = makeCredential({
      enabled_models: ['openai/gpt-4o', 'production-gpt4'],
    })

    const resolution = resolveLLMModelsForCredential(credential, [])

    expect(resolution).toEqual({
      mode: 'catalog',
      models: ['openai/gpt-4o', 'production-gpt4'],
    })
  })

  it('prefers gateway_direct when custom provider has gateway_model', () => {
    const credential = makeCredential({
      gateway_model: 'openai/gpt-4.1',
      enabled_models: ['openai/gpt-4o'],
    })

    const resolution = resolveLLMModelsForCredential(credential, [])

    expect(resolution).toEqual({
      mode: 'gateway_direct',
      model: 'openai/gpt-4.1',
    })
  })

  it('intersects catalog with enabled_models allowlist', () => {
    const credential = makeCredential({
      provider: 'openai',
      gateway_model: undefined,
      enabled_models: ['gpt-4o', 'gpt-4o-mini'],
    })
    const catalog = [
      'gpt-4o',
      'gpt-4o-mini',
      'gpt-4.1',
      'gpt-5-mini',
      'o3-mini',
    ]

    const resolution = resolveLLMModelsForCredential(credential, catalog)

    expect(resolution).toEqual({
      mode: 'catalog',
      models: ['gpt-4o', 'gpt-4o-mini'],
    })
  })

  it('returns allowlist when catalog is empty for non-custom provider', () => {
    const credential = makeCredential({
      provider: 'fireworks',
      gateway_model: undefined,
      enabled_models: ['accounts/fireworks/models/gpt-oss-120b'],
    })

    const resolution = resolveLLMModelsForCredential(credential, [])

    expect(resolution).toEqual({
      mode: 'catalog',
      models: ['accounts/fireworks/models/gpt-oss-120b'],
    })
  })
})

describe('classification model helpers', () => {
  it('accepts Jev models for classification and rejects Tev / standard models', () => {
    expect(isClassificationCapableModel('typesafe/jev-1.13.0')).toBe(true)
    expect(isClassificationCapableModel('openrouter/typesafe/JEV-latest')).toBe(true)
    expect(isClassificationCapableModel('typesafe/tev-1')).toBe(false)
    expect(isClassificationCapableModel('gpt-4o')).toBe(false)
  })

  it('allows standard chat and Together Tev models; excludes Jev for classification picker', () => {
    expect(isStandardJudgeModel('gpt-4o')).toBe(true)
    expect(isStandardJudgeModel('anthropic/claude-sonnet-5-5')).toBe(true)
    expect(isStandardJudgeModel('typesafe/jev-1.13.0')).toBe(false)
    expect(isStandardJudgeModel('typesafe/tev-1')).toBe(true)
    expect(isStandardJudgeModel('together/Tev1-4B-experimental')).toBe(true)
  })

  it('detects classification metrics by custom_data_type', () => {
    expect(isClassificationMetric({ custom_data_type: 'classification' })).toBe(true)
    expect(isClassificationMetric({ custom_data_type: 'enum' })).toBe(false)
    expect(isClassificationMetric({})).toBe(false)
  })
})

describe('seedClassificationLLM', () => {
  const runLevel = { provider: 'openai', model: 'gpt-4o', credential_id: 'c-openai' }

  it('reuses an existing Jev override on a classification metric', () => {
    const seeded = seedClassificationLLM(
      ['m-class'],
      { 'm-class': { provider: 'openrouter', model: 'typesafe/jev-1.13', credential_id: 'c-or' } },
      runLevel,
    )
    expect(seeded).toMatchObject({ provider: 'openrouter', model: 'typesafe/jev-1.13', credential_id: 'c-or' })
  })

  it('falls back to the run-level model only when it is a Jev model', () => {
    expect(seedClassificationLLM(['m-class'], null, runLevel).model).toBeNull()
    expect(
      seedClassificationLLM(['m-class'], null, { provider: 'typesafe', model: 'jev-1.13.0' }).model,
    ).toBe('jev-1.13.0')
  })
})

describe('mergeClassificationOverrides', () => {
  it('keeps existing overrides, sets classification metrics, and drops unknown ids', () => {
    const merged = mergeClassificationOverrides(
      {
        'm-std': { provider: 'anthropic', model: 'claude-sonnet-5-5' },
        'm-gone': { provider: 'openai', model: 'gpt-4o' },
      },
      ['m-class', 'm-not-in-run'],
      ['m-std', 'm-class'],
      { provider: 'typesafe', model: 'jev-1.13.0', credential_id: 'c-ts' },
    )
    expect(Object.keys(merged).sort()).toEqual(['m-class', 'm-std'])
    expect(merged['m-std'].model).toBe('claude-sonnet-5-5')
    expect(merged['m-class']).toMatchObject({ provider: 'typesafe', model: 'jev-1.13.0', credential_id: 'c-ts' })
  })
})
