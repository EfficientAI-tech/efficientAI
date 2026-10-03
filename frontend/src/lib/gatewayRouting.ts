import type { AIProvider } from '../types/api'

type GatewayCredential = Pick<
  AIProvider,
  'id' | 'provider' | 'gateway_model' | 'routing_mode' | 'effective_routing'
>

export function routesViaGateway(
  credential?: GatewayCredential | null,
): boolean {
  if (!credential) return false
  const effective = credential.effective_routing
  if (
    effective === 'bifrost' ||
    effective === 'litellm_proxy' ||
    effective === 'gateway'
  ) {
    return true
  }
  return credential.routing_mode === 'gateway'
}

export function usesGatewayDirectModel(
  credential?: GatewayCredential | null,
): boolean {
  const gatewayModel = credential?.gateway_model?.trim()
  if (!gatewayModel) return false
  return routesViaGateway(credential)
}

export function resolveActiveAIProvider(
  aiProviders: AIProvider[],
  providerKey: string,
  credentialId?: string | null,
): AIProvider | undefined {
  const normalizedKey = providerKey.toLowerCase()
  const rows = aiProviders.filter(
    (p) =>
      p.is_active &&
      String(p.provider ?? '').toLowerCase() === normalizedKey,
  )
  if (credentialId) {
    return rows.find((p) => p.id === credentialId)
  }
  return rows.find((p) => p.is_default) ?? rows[0]
}

export type ResolvedGatewayType = 'bifrost' | 'litellm_proxy'

export const GATEWAY_TYPE_LABELS: Record<ResolvedGatewayType, string> = {
  bifrost: 'Bifrost',
  litellm_proxy: 'LiteLLM Proxy',
}

type GatewayFieldCopy = {
  /** Whether the Bifrost API surface (shim vs native) selector applies. */
  supportsInterface: boolean
  modelHelp: string
  customModelHelp: string
  baseUrlPlaceholder: string
  authHeaderPlaceholder: string
  authHeaderHelp: string
  authSecretEnvPlaceholder: string
  authSecretEnvHelp: string
}

/** Per-gateway copy for the credential gateway fields. Add an entry to support a new gateway. */
export const GATEWAY_FIELD_COPY: Record<ResolvedGatewayType, GatewayFieldCopy> = {
  bifrost: {
    supportsInterface: true,
    modelHelp: 'Bifrost custom model ID sent when routing via gateway. Leave blank to use the workload-selected model.',
    customModelHelp: 'Bifrost model ID for this integration. Each custom credential pins one model.',
    baseUrlPlaceholder: 'e.g. http://localhost:8080',
    authHeaderPlaceholder: 'x-bf-vk',
    authHeaderHelp: 'Header name for Bifrost auth. Defaults to x-bf-vk when blank.',
    authSecretEnvPlaceholder: 'BIFROST_VIRTUAL_KEY',
    authSecretEnvHelp:
      'Read the auth secret from this environment variable at runtime (e.g. K8s secret). Overrides org virtual key.',
  },
  litellm_proxy: {
    supportsInterface: false,
    modelHelp:
      'LiteLLM Proxy model alias (model_name in the proxy config). Leave blank to use the workload-selected model.',
    customModelHelp: 'LiteLLM Proxy model alias for this integration. Each custom credential pins one model.',
    baseUrlPlaceholder: 'e.g. http://localhost:4000',
    authHeaderPlaceholder: 'Authorization',
    authHeaderHelp: 'Header name for LiteLLM Proxy auth. Defaults to Authorization (Bearer added automatically).',
    authSecretEnvPlaceholder: 'LITELLM_API_KEY',
    authSecretEnvHelp:
      'Read the LiteLLM key from this environment variable at runtime (e.g. K8s secret). Overrides org master key.',
  },
}
