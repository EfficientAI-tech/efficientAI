import { getProviderLabel } from '../../config/providers'
import type { AIProvider } from '../../types/api'

export type PricingUsageKind = 'llm' | 'stt' | 'tts'

export type ProviderModelCatalog = {
  llm?: string[]
  stt?: string[]
  tts?: string[]
  s2s?: string[]
}

export function credentialDisplayLabel(credential: AIProvider): string {
  const providerLabel = getProviderLabel(credential.provider)
  const name = credential.name?.trim()
  return name ? `${providerLabel} — ${name}` : providerLabel
}

export function modelsForCredentialAndKind(
  credential: AIProvider,
  catalog: ProviderModelCatalog,
  kind: PricingUsageKind,
): string[] {
  const catalogModels = [...(catalog[kind] || [])]
  const allowlist = credential.enabled_models?.map((m) => m.trim()).filter(Boolean) ?? []
  const gateway = credential.gateway_model?.trim()

  if (allowlist.length > 0) {
    const allowed = new Set(allowlist)
    let filtered = catalogModels.filter((m) => allowed.has(m))
    if (kind === 'llm' && gateway && !filtered.includes(gateway)) {
      filtered = [gateway, ...filtered]
    }
    return filtered.sort()
  }

  if (kind === 'llm' && gateway && !catalogModels.includes(gateway)) {
    return [gateway, ...catalogModels].sort()
  }

  return catalogModels.sort()
}

export function buildPricingModelOptions(params: {
  credential: AIProvider | undefined
  catalog: ProviderModelCatalog | undefined
  kind: PricingUsageKind
  eligibleModels: Set<string>
  overrideModels: string[]
}): Array<{ id: string; label: string }> {
  const { credential, catalog, kind, eligibleModels, overrideModels } = params
  if (!credential || !catalog) return []

  const fromCatalog = modelsForCredentialAndKind(credential, catalog, kind)
  const catalogSet = new Set(catalog[kind] || [])
  const allowlist = new Set(
    credential.enabled_models?.map((m) => m.trim()).filter(Boolean) ?? [],
  )

  const extras = overrideModels.filter((model) => {
    if (fromCatalog.includes(model)) return false
    if (!eligibleModels.has(model)) return false
    if (catalogSet.has(model)) return true
    if (allowlist.has(model)) return true
    if (kind === 'llm' && credential.gateway_model?.trim() === model) return true
    return false
  })

  return Array.from(new Set([...fromCatalog, ...extras]))
    .sort()
    .map((name) => ({ id: name, label: name }))
}
