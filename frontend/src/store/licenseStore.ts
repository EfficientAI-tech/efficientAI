import { create } from 'zustand'
import { apiClient } from '../lib/api'
import type { EnterpriseFeatureCatalog, EnterpriseFeatureMeta } from '../lib/api'

interface LicenseState {
  isEnterprise: boolean
  enabledFeatures: string[]
  allEnterpriseFeatures: string[]
  featureCatalog: EnterpriseFeatureCatalog
  isLoaded: boolean
  fetchLicense: () => Promise<void>
  isFeatureEnabled: (feature: string) => boolean
  getFeatureMeta: (feature: string) => EnterpriseFeatureMeta | undefined
}

export const useLicenseStore = create<LicenseState>((set, get) => ({
  isEnterprise: false,
  enabledFeatures: [],
  allEnterpriseFeatures: [],
  featureCatalog: {},
  isLoaded: false,

  fetchLicense: async () => {
    try {
      const info = await apiClient.getLicenseInfo()
      set({
        isEnterprise: info.is_enterprise,
        enabledFeatures: info.enabled_features,
        allEnterpriseFeatures: info.all_enterprise_features,
        featureCatalog: info.feature_catalog ?? {},
        isLoaded: true,
      })
    } catch {
      set({
        isEnterprise: false,
        enabledFeatures: [],
        allEnterpriseFeatures: [],
        featureCatalog: {},
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
}))
