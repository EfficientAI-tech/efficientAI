import { create } from 'zustand'
import { apiClient } from '../lib/api'
import type { EnterpriseFeatureCatalog, EnterpriseFeatureMeta, UsagePolicy } from '../lib/api'

const DEFAULT_USAGE_POLICY: UsagePolicy = {
  extended_history: false,
  max_history_days: 7,
}

interface LicenseState {
  isEnterprise: boolean
  enabledFeatures: string[]
  allEnterpriseFeatures: string[]
  featureCatalog: EnterpriseFeatureCatalog
  usagePolicy: UsagePolicy
  isLoaded: boolean
  fetchLicense: () => Promise<void>
  isFeatureEnabled: (feature: string) => boolean
  getFeatureMeta: (feature: string) => EnterpriseFeatureMeta | undefined
  hasExtendedUsageHistory: () => boolean
}

export const useLicenseStore = create<LicenseState>((set, get) => ({
  isEnterprise: false,
  enabledFeatures: [],
  allEnterpriseFeatures: [],
  featureCatalog: {},
  usagePolicy: DEFAULT_USAGE_POLICY,
  isLoaded: false,

  fetchLicense: async () => {
    try {
      const info = await apiClient.getLicenseInfo()
      set({
        isEnterprise: info.is_enterprise,
        enabledFeatures: info.enabled_features,
        allEnterpriseFeatures: info.all_enterprise_features,
        featureCatalog: info.feature_catalog ?? {},
        usagePolicy: info.usage_policy ?? DEFAULT_USAGE_POLICY,
        isLoaded: true,
      })
    } catch {
      set({
        isEnterprise: false,
        enabledFeatures: [],
        allEnterpriseFeatures: [],
        featureCatalog: {},
        usagePolicy: DEFAULT_USAGE_POLICY,
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
