export const JEV_PROVIDER_ALLOWLIST = [
  'together',
  'typesafe',
  'openrouter',
] as const

/** LiteLLM / OpenRouter slugs for TypeSafe Jev (catalog keys are unprefixed). */
export const TYPESAFE_JEV_SLUGS = [
  'typesafe/jev-1.13.0',
  'typesafe/jev-latest',
  'typesafe/jev-preview',
] as const

const JEV_NAME_RE = /tev1|(?:^|\/)jev(?:[-/]|$)/i

export function isJevModel(
  provider?: string | null,
  model?: string | null,
): boolean {
  const name = (model || '').trim()
  if (!name) return false
  const providerKey = (provider || '').trim().toLowerCase()
  if (providerKey === 'typesafe') return true
  return JEV_NAME_RE.test(name)
}

export function extraJevModelsForProvider(provider?: string | null): string[] {
  const key = (provider || '').trim().toLowerCase()
  if (key === 'openrouter' || key === 'typesafe') {
    return [...TYPESAFE_JEV_SLUGS]
  }
  return []
}
