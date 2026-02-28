import { create } from 'zustand'
import { apiClient } from '../lib/api'

interface LicenseState {
  isEnterprise: boolean
  enabledFeatures: string[]
  allEnterpriseFeatures: string[]
  isLoaded: boolean
  fetchLicense: () => Promise<void>
  isFeatureEnabled: (feature: string) => boolean
}

export const useLicenseStore = create<LicenseState>((set, get) => ({
  isEnterprise: false,
  enabledFeatures: [],
  allEnterpriseFeatures: [],
  isLoaded: false,

  fetchLicense: async () => {
    try {
      const info = await apiClient.getLicenseInfo()
      set({
        isEnterprise: info.is_enterprise,
        enabledFeatures: info.enabled_features,
        allEnterpriseFeatures: info.all_enterprise_features,
        isLoaded: true,
      })
    } catch {
      set({
        isEnterprise: false,
        enabledFeatures: [],
        allEnterpriseFeatures: [],
        isLoaded: true,
      })
    }
  },

  isFeatureEnabled: (feature: string) => {
    return get().enabledFeatures.includes(feature)
  },
}))
