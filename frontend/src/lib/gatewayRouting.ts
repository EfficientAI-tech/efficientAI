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
  const rows = aiProviders.filter(
    (p) => p.is_active && p.provider.toLowerCase() === providerKey.toLowerCase(),
  )
  if (credentialId) {
    return rows.find((p) => p.id === credentialId)
  }
  return rows.find((p) => p.is_default) ?? rows[0]
}
