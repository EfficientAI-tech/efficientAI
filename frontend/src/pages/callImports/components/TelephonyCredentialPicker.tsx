import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { apiClient } from '../../../lib/api'

export const DIRECT_URL_CREDENTIAL = '__none__'

export interface TelephonyCredentialSelection {
  provider: string | null
  telephonyIntegrationId: string | null
}

interface TelephonyCredentialPickerProps {
  selectedProvider: string
  selectedIntegrationId: string
  onProviderChange: (provider: string) => void
  onIntegrationChange: (integrationId: string) => void
  disabled?: boolean
  /** Shorter copy for compact modals. */
  compact?: boolean
}

export function isCredentialSelectionValid(
  selectedProvider: string,
  selectedIntegrationId: string,
): boolean {
  if (selectedIntegrationId === DIRECT_URL_CREDENTIAL) return true
  return !!selectedProvider && !!selectedIntegrationId
}

export function credentialSelectionFromState(
  selectedProvider: string,
  selectedIntegrationId: string,
): TelephonyCredentialSelection {
  if (selectedIntegrationId === DIRECT_URL_CREDENTIAL) {
    return { provider: null, telephonyIntegrationId: null }
  }
  return {
    provider: selectedProvider || null,
    telephonyIntegrationId: selectedIntegrationId || null,
  }
}

/**
 * Shared telephony provider + credential picker used for import start and
 * retry-failed flows.
 */
export default function TelephonyCredentialPicker({
  selectedProvider,
  selectedIntegrationId,
  onProviderChange,
  onIntegrationChange,
  disabled = false,
  compact = false,
}: TelephonyCredentialPickerProps) {
  const { data: telephonyConfigs = [] } = useQuery({
    queryKey: ['telephony-configs'],
    queryFn: () => apiClient.listTelephonyConfigs(),
  })

  const activeConfigs = useMemo(
    () => telephonyConfigs.filter((cfg) => cfg.is_active),
    [telephonyConfigs],
  )

  const providers = useMemo(() => {
    return Array.from(
      new Set(activeConfigs.map((cfg) => cfg.provider).filter(Boolean)),
    )
  }, [activeConfigs])

  const integrationOptions = useMemo(() => {
    return activeConfigs.filter((cfg) => cfg.provider === selectedProvider)
  }, [activeConfigs, selectedProvider])

  const useDirectUrl = selectedIntegrationId === DIRECT_URL_CREDENTIAL

  return (
    <div className="space-y-4">
      {!compact && (
        <p className="text-sm text-gray-600">
          {useDirectUrl
            ? 'Recordings will be downloaded directly from each row’s recording URL.'
            : 'Pick the telephony provider and credential to use when fetching recordings.'}
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Telephony Provider{' '}
            {!useDirectUrl && <span className="text-red-500">*</span>}
          </label>
          <select
            value={selectedProvider}
            onChange={(e) => {
              onProviderChange(e.target.value)
              onIntegrationChange('')
            }}
            disabled={useDirectUrl || disabled}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 disabled:bg-gray-100"
          >
            <option value="">Select provider</option>
            {providers.map((provider) => (
              <option key={provider} value={provider}>
                {provider}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Integration Credential <span className="text-red-500">*</span>
          </label>
          <select
            value={selectedIntegrationId}
            onChange={(e) => {
              const next = e.target.value
              onIntegrationChange(next)
              if (next === DIRECT_URL_CREDENTIAL) {
                onProviderChange('')
              }
            }}
            disabled={disabled}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 disabled:bg-gray-100"
          >
            <option value="">Select credential</option>
            <option value={DIRECT_URL_CREDENTIAL}>
              None — use recording URLs from CSV
            </option>
            {selectedProvider &&
              integrationOptions.map((cfg) => (
                <option key={cfg.id} value={cfg.id}>
                  {cfg.name || `${cfg.provider} (${cfg.id.slice(0, 8)})`}
                </option>
              ))}
          </select>
        </div>
      </div>

      {providers.length === 0 && !useDirectUrl && (
        <div className="rounded-md bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800 space-y-2">
          <p>
            No telephony credentials are configured. Choose &ldquo;None — use
            recording URLs from CSV&rdquo; if rows include direct links, or
            configure credentials below.
          </p>
          <Link
            to="/integrations"
            className="inline-block font-medium text-amber-900 underline hover:text-amber-700"
          >
            Configure telephony credentials in Integrations &rarr;
          </Link>
        </div>
      )}
    </div>
  )
}
