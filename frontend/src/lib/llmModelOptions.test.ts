import { describe, expect, it } from 'vitest'
import { resolveLLMModelsForCredential } from './llmModelOptions'
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
