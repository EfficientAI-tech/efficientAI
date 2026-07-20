import type { AIProvider } from '../types/api'
import { resolveActiveAIProvider, routesViaGateway, usesGatewayDirectModel } from './gatewayRouting'

/** Substring fingerprints for chat models that accept audio input. */
export const AUDIO_CAPABLE_MODEL_MATCHERS: Record<string, RegExp[]> = {
  openai: [/audio/i, /realtime/i],
  google: [/^gemini-(1\.5|[2-9])/i],
}

export const AUDIO_CAPABLE_PROVIDERS = Object.keys(AUDIO_CAPABLE_MODEL_MATCHERS)

export type LLMModelResolution =
  | { mode: 'gateway_direct'; model: string }
  | { mode: 'catalog'; models: string[] }

export function isAudioCapableModel(provider: string, model: string): boolean {
  const matchers = AUDIO_CAPABLE_MODEL_MATCHERS[provider.toLowerCase()]
  if (!matchers) return false
  return matchers.some((re) => re.test(model))
}

/** True when an active credential pins a gateway-routed Bifrost model. */
export function hasGatewayLLMCredential(
  aiProviders: AIProvider[],
  provider: string,
): boolean {
  const key = provider.toLowerCase()
  return aiProviders.some((p) => {
    if (!p.is_active || p.provider.toLowerCase() !== key) return false
    const gatewayModel = p.gateway_model?.trim()
    if (!gatewayModel) return false
    if (key === 'custom') return true
    return routesViaGateway(p)
  })
}

/** Provider is selectable for LLM when catalog or gateway credentials exist. */
export function providerHasLLMModels(
  provider: string,
  catalogModels: string[],
  aiProviders: AIProvider[],
): boolean {
  return catalogModels.length > 0 || hasGatewayLLMCredential(aiProviders, provider)
}

export function resolveLLMModelsForCredential(
  credential: AIProvider | undefined,
  catalogModels: string[],
): LLMModelResolution {
  const gatewayModel = credential?.gateway_model?.trim()
  const providerKey = String(credential?.provider ?? '').toLowerCase()
  if (providerKey === 'custom' && gatewayModel) {
    return { mode: 'gateway_direct', model: gatewayModel }
  }
  if (credential && usesGatewayDirectModel(credential) && gatewayModel) {
    return { mode: 'gateway_direct', model: gatewayModel }
  }
  if (
    gatewayModel &&
    credential &&
    routesViaGateway(credential) &&
    catalogModels.length === 0
  ) {
    return { mode: 'gateway_direct', model: gatewayModel }
  }
  return { mode: 'catalog', models: catalogModels }
}

/** Gateway-routed custom credentials are allowed for multimodal diariser. */
export function isGatewayAudioCapableCredential(
  credential: AIProvider,
): boolean {
  const gatewayModel = credential.gateway_model?.trim()
  const provider = credential.provider?.toLowerCase() ?? ''

  // Custom Bifrost integrations: any configured gateway model may be
  // used for LLM-only diarisation — audio support is operator-owned.
  if (provider === 'custom') {
    return Boolean(gatewayModel)
  }

  if (!gatewayModel) return false
  if (!['openai', 'google'].includes(provider)) return false

  if (routesViaGateway(credential)) return true
  return isAudioCapableModel(provider, gatewayModel)
}

export function isAudioCapableSelection(
  provider: string,
  model: string | null,
  credential?: AIProvider | null,
): boolean {
  if (credential && usesGatewayDirectModel(credential)) {
    return isGatewayAudioCapableCredential(credential)
  }
  if (credential && isGatewayAudioCapableCredential(credential)) {
    return true
  }
  if (!model) return false
  return isAudioCapableModel(provider, model)
}

export interface LLMProviderFilterOptions {
  providerAllowList?: string[]
  audioCapableOnly?: boolean
}

export function buildLLMProviderKeys(
  aiProviders: AIProvider[],
  integrationProviderKeys: string[],
  filters?: LLMProviderFilterOptions,
): string[] {
  const providerKeys = new Set<string>()

  for (const p of aiProviders) {
    if (!p.is_active) continue
    providerKeys.add((p.provider || '').toLowerCase())
  }
  for (const key of integrationProviderKeys) {
    if (key) providerKeys.add(key.toLowerCase())
  }

  let keys = Array.from(providerKeys)

  const allowSet = filters?.providerAllowList
    ? new Set(filters.providerAllowList.map((p) => p.toLowerCase()))
    : null

  if (filters?.audioCapableOnly) {
    const audioKeys = new Set(AUDIO_CAPABLE_PROVIDERS)
    for (const p of aiProviders) {
      if (p.is_active && isGatewayAudioCapableCredential(p)) {
        audioKeys.add(p.provider.toLowerCase())
      }
    }
    keys = keys.filter((k) => audioKeys.has(k))
  }

  if (allowSet) {
    keys = keys.filter((k) => allowSet.has(k))
  }

  return keys
}

/** Show credential picker for custom or when any gateway-only model exists. */
export function shouldAlwaysShowCredentialPicker(
  provider: string,
  aiProviders: AIProvider[],
): boolean {
  const key = provider.toLowerCase()
  if (key === 'custom') return true
  const rows = aiProviders.filter(
    (p) => p.is_active && p.provider.toLowerCase() === key,
  )
  if (rows.length === 0) return false
  return rows.some((p) => {
    const resolution = resolveLLMModelsForCredential(p, [])
    return resolution.mode === 'gateway_direct'
  })
}

export function formatGatewayCredentialLabel(
  credential: Pick<AIProvider, 'provider' | 'name' | 'gateway_model' | 'is_default'>,
  providerLabels: Record<string, string>,
): string {
  const base =
    providerLabels[credential.provider.toLowerCase()] ||
    credential.provider
  const named = credential.name ? ` — ${credential.name}` : ''
  const defaultTag = credential.is_default ? ' (default)' : ''
  const gateway = credential.gateway_model?.trim()
  const gatewayTag = gateway ? ` · ${gateway}` : ''
  return `${base}${named}${defaultTag}${gatewayTag}`
}

export interface LLMSelectionValue {
  provider: string | null
  model: string | null
  credential_id?: string | null
}

const DEFAULT_LLM_MODELS: Record<string, string> = {
  openai: 'gpt-5-mini',
  anthropic: 'claude-sonnet-4.6',
  google: 'gemini-2.5-flash',
  sarvam: 'sarvam-30b',
}

function resolveCredentialForSelection(
  selection: LLMSelectionValue,
  aiProviders: AIProvider[],
): AIProvider | undefined {
  if (selection.credential_id) {
    const pinned = aiProviders.find(
      (p) => p.is_active && p.id === selection.credential_id,
    )
    if (pinned) return pinned
  }
  if (!selection.provider) return undefined
  return resolveActiveAIProvider(
    aiProviders,
    selection.provider,
    selection.credential_id,
  )
}

/** True when provider is set and a catalog or gateway model is resolved. */
export function isLLMSelectionComplete(
  selection: LLMSelectionValue,
  aiProviders: AIProvider[],
): boolean {
  if (!selection.provider && !selection.credential_id) return false
  if (selection.model?.trim()) return true

  const credential = resolveCredentialForSelection(selection, aiProviders)
  if (!credential) return false

  const resolution = resolveLLMModelsForCredential(credential, [])
  if (resolution.mode === 'gateway_direct') return true

  // Gateway-routed credentials without a pinned gateway_model still
  // resolve at request time (same as partials / metrics surfaces).
  if (routesViaGateway(credential)) return true

  return false
}

/** True when the selection is half-filled (not empty default, not complete). */
export function isLLMSelectionPartial(
  selection: LLMSelectionValue,
  aiProviders: AIProvider[],
): boolean {
  const hasAnySelection = Boolean(
    selection.provider || selection.model?.trim() || selection.credential_id,
  )
  if (!hasAnySelection) return false
  return !isLLMSelectionComplete(selection, aiProviders)
}

/** Model string to send to APIs when gateway routing pins the model. */
export function resolveLLMModelForSubmit(
  selection: LLMSelectionValue,
  aiProviders: AIProvider[],
): string | null {
  if (selection.model?.trim()) return selection.model.trim()

  const credential = resolveCredentialForSelection(selection, aiProviders)
  if (!credential) return null

  const resolution = resolveLLMModelsForCredential(credential, [])
  if (resolution.mode === 'gateway_direct') return resolution.model

  if (routesViaGateway(credential)) {
    const gatewayModel = credential.gateway_model?.trim()
    if (gatewayModel) return gatewayModel
    const providerKey = (credential.provider || selection.provider || '')
      .toLowerCase()
      .trim()
    return DEFAULT_LLM_MODELS[providerKey] ?? 'gpt-5-mini'
  }

  return null
}
