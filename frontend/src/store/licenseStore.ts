import { create } from 'zustand'
import { apiClient } from '../lib/api'
import type {
  EnterpriseFeatureCatalog,
  EnterpriseFeatureMeta,
  OssQuotaUsage,
  OssQuotas,
  UsagePolicy,
} from '../lib/api'

const DEFAULT_USAGE_POLICY: UsagePolicy = {
  extended_history: false,
  max_history_days: 7,
}

const DEFAULT_OSS_QUOTAS: OssQuotas = {
  max_user_metrics: 5,
  max_agents: 3,
  max_org_members: 1,
  max_workspaces: 1,
}

const DEFAULT_QUOTA_USAGE: OssQuotaUsage = {
  user_metrics: 0,
  agents: 0,
  org_members: 0,
  workspaces: 0,
}

interface LicenseState {
  isEnterprise: boolean
  gatewayRoutingAllowed: boolean
  enabledFeatures: string[]
  allEnterpriseFeatures: string[]
  featureCatalog: EnterpriseFeatureCatalog
  usagePolicy: UsagePolicy
  quotas: OssQuotas | null
  quotaUsage: OssQuotaUsage | null
  isLoaded: boolean
  fetchLicense: () => Promise<void>
  isFeatureEnabled: (feature: string) => boolean
  getFeatureMeta: (feature: string) => EnterpriseFeatureMeta | undefined
  hasExtendedUsageHistory: () => boolean
}

export const useLicenseStore = create<LicenseState>((set, get) => ({
  isEnterprise: false,
  gatewayRoutingAllowed: false,
  enabledFeatures: [],
  allEnterpriseFeatures: [],
  featureCatalog: {},
  usagePolicy: DEFAULT_USAGE_POLICY,
  quotas: DEFAULT_OSS_QUOTAS,
  quotaUsage: DEFAULT_QUOTA_USAGE,
  isLoaded: false,

  fetchLicense: async () => {
    try {
      const info = await apiClient.getLicenseInfo()
      set({
        isEnterprise: info.is_enterprise,
        gatewayRoutingAllowed: info.gateway_routing_allowed ?? info.is_enterprise,
        enabledFeatures: info.enabled_features,
        allEnterpriseFeatures: info.all_enterprise_features,
        featureCatalog: info.feature_catalog ?? {},
        usagePolicy: info.usage_policy ?? DEFAULT_USAGE_POLICY,
        quotas: info.is_enterprise ? null : (info.quotas ?? DEFAULT_OSS_QUOTAS),
        quotaUsage: info.quota_usage ?? DEFAULT_QUOTA_USAGE,
        isLoaded: true,
      })
    } catch {
      set({
        isEnterprise: false,
        gatewayRoutingAllowed: false,
        enabledFeatures: [],
        allEnterpriseFeatures: [],
        featureCatalog: {},
        usagePolicy: DEFAULT_USAGE_POLICY,
        quotas: DEFAULT_OSS_QUOTAS,
        quotaUsage: DEFAULT_QUOTA_USAGE,
        isLoaded: true,
      })
    }
  },

  isFeatureEnabled: (feature: string) => {
    return get().enabledFeatures.includes(feature)
  },

  getFeatureMeta: (feature: string) => {
    return get().featureCatalog[feature]
  },

  hasExtendedUsageHistory: () => {
    return get().usagePolicy.extended_history
  },
}))
