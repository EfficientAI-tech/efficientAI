import { useQuery } from '@tanstack/react-query'
import { apiClient, TelephonyIntegrationResponse, TelephonyPhoneNumberResponse } from '../lib/api'

export function useOrgTelephony(enabled = true) {
  const { data: telephonyConfigs = [], isLoading: configsLoading } = useQuery<TelephonyIntegrationResponse[]>({
    queryKey: ['telephony-configs'],
    queryFn: () => apiClient.listTelephonyConfigs(),
    enabled,
    retry: false,
  })

  const { data: telephonyNumbers = [], isLoading: numbersLoading } = useQuery<TelephonyPhoneNumberResponse[]>({
    queryKey: ['telephony-numbers'],
    queryFn: () => apiClient.listTelephonyNumbers(),
    enabled,
    retry: false,
  })

  const activeConfigs = telephonyConfigs.filter((cfg) => cfg.is_active)
  const hasTelephony = activeConfigs.length > 0
  const defaultConfig =
    activeConfigs.find((cfg) => cfg.is_default) || activeConfigs[0] || null

  const activeNumbers = telephonyNumbers.filter((n) => n.is_active)
  const inboundNumbers = activeNumbers.filter((n) => n.inbound_enabled)
  const outboundNumbers = activeNumbers.filter((n) => n.outbound_enabled)

  return {
    telephonyConfigs,
    telephonyNumbers,
    activeConfigs,
    activeNumbers,
    inboundNumbers,
    outboundNumbers,
    hasTelephony,
    defaultConfig,
    isLoading: configsLoading || numbersLoading,
  }
}
