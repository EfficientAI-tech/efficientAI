import {
  IntegrationPlatform,
  ModelProvider,
} from '../types/api'
import {
  getIntegrationPlatformLogo,
  getProviderLogo,
} from '../config/providers'

/** Logo path for a lowercase provider / integration platform key. */
export function logoUrlForProviderKey(providerKey: string): string | null {
  const key = (providerKey || '').toLowerCase().trim()
  if (!key) return null

  const model = Object.values(ModelProvider).find((p) => p === key) as
    | ModelProvider
    | undefined
  if (model) return getProviderLogo(model)

  const platform = Object.values(IntegrationPlatform).find((p) => p === key) as
    | IntegrationPlatform
    | undefined
  if (platform) return getIntegrationPlatformLogo(platform)

  return null
}
