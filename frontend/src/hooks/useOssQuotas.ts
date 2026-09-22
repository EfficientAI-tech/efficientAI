import { useLicenseStore } from '../store/licenseStore'

export type OssQuotaResource = 'user_metrics' | 'agents' | 'org_members' | 'workspaces'

const QUOTA_KEY: Record<OssQuotaResource, keyof NonNullable<ReturnType<typeof useLicenseStore.getState>['quotas']>> = {
  user_metrics: 'max_user_metrics',
  agents: 'max_agents',
  org_members: 'max_org_members',
  workspaces: 'max_workspaces',
}

const USAGE_KEY: Record<OssQuotaResource, keyof NonNullable<ReturnType<typeof useLicenseStore.getState>['quotaUsage']>> = {
  user_metrics: 'user_metrics',
  agents: 'agents',
  org_members: 'org_members',
  workspaces: 'workspaces',
}

export function useOssQuotas() {
  const quotas = useLicenseStore((s) => s.quotas)
  const quotaUsage = useLicenseStore((s) => s.quotaUsage)
  const isEnterprise = useLicenseStore((s) => s.isEnterprise)

  const isAtLimit = (resource: OssQuotaResource): boolean => {
    if (isEnterprise || !quotas || !quotaUsage) return false
    const limit = quotas[QUOTA_KEY[resource]]
    if (limit == null) return false
    return quotaUsage[USAGE_KEY[resource]] >= limit
  }

  const remaining = (resource: OssQuotaResource): number | null => {
    if (isEnterprise || !quotas || !quotaUsage) return null
    const limit = quotas[QUOTA_KEY[resource]]
    if (limit == null) return null
    return Math.max(0, limit - quotaUsage[USAGE_KEY[resource]])
  }

  const limitMessage = (resource: OssQuotaResource): string => {
    const messages: Record<OssQuotaResource, string> = {
      user_metrics:
        'Open source limit: 5 user-created metrics. Upgrade with EFFICIENTAI_LICENSE for unlimited metrics.',
      agents: 'Open source limit: 3 agents. Upgrade with EFFICIENTAI_LICENSE for unlimited agents.',
      org_members:
        'Open source limit: 1 organization member (solo use). Upgrade with EFFICIENTAI_LICENSE to invite more users.',
      workspaces:
        'Open source limit: 1 workspace. Upgrade with EFFICIENTAI_LICENSE to create additional workspaces.',
    }
    return messages[resource]
  }

  return { isAtLimit, remaining, limitMessage, isEnterprise }
}
