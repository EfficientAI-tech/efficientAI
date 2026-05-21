import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, PlayCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { apiClient } from '../../../lib/api'
import type { CallImport } from '../../../types/api'
import Button from '../../../components/Button'

interface ImportPanelProps {
  callImport: CallImport
}

/**
 * IMPORT-stage form on the call-import detail page.
 *
 * Lets the user pick a telephony provider + credential and kick off
 * the actual import (materialising rows + enqueuing per-row Celery
 * jobs). Only rendered when the batch is in ``mapped`` state.
 */
export default function ImportPanel({ callImport }: ImportPanelProps) {
  const queryClient = useQueryClient()
  const [selectedProvider, setSelectedProvider] = useState('')
  const [selectedIntegrationId, setSelectedIntegrationId] = useState('')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [integrationHint, setIntegrationHint] = useState(false)

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

  const startMutation = useMutation({
    mutationFn: () =>
      apiClient.startCallImport(callImport.id, {
        provider: selectedProvider,
        telephonyIntegrationId: selectedIntegrationId,
      }),
    onSuccess: () => {
      setSubmitError(null)
      setIntegrationHint(false)
      queryClient.invalidateQueries({ queryKey: ['call-import', callImport.id] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      const message =
        detail || err?.message || 'Failed to start import.'
      setSubmitError(message)
      if (detail && /credential|integration/i.test(detail)) {
        setIntegrationHint(true)
      }
    },
  })

  const canSubmit =
    !!selectedProvider && !!selectedIntegrationId && !startMutation.isPending

  return (
    <div className="bg-white shadow rounded-lg p-6 space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <PlayCircle className="h-5 w-5 text-primary-600" />
          Start import
        </h2>
        <p className="text-sm text-gray-600 mt-1">
          Pick the telephony provider + credential to use when fetching
          recordings for this batch. Once started, the per-row workers
          pick up automatically and progress is reflected on this page.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Telephony Provider <span className="text-red-500">*</span>
          </label>
          <select
            value={selectedProvider}
            onChange={(e) => {
              setSelectedProvider(e.target.value)
              setSelectedIntegrationId('')
            }}
            disabled={startMutation.isPending}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
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
            onChange={(e) => setSelectedIntegrationId(e.target.value)}
            disabled={!selectedProvider || startMutation.isPending}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 disabled:bg-gray-100"
          >
            <option value="">Select credential</option>
            {integrationOptions.map((cfg) => (
              <option key={cfg.id} value={cfg.id}>
                {cfg.name || `${cfg.provider} (${cfg.id.slice(0, 8)})`}
              </option>
            ))}
          </select>
        </div>
      </div>

      {providers.length === 0 && (
        <div className="rounded-md bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800 space-y-2">
          <p>No telephony credentials are configured for this workspace.</p>
          <Link
            to="/integrations"
            className="inline-block font-medium text-amber-900 underline hover:text-amber-700"
          >
            Configure telephony credentials in Integrations &rarr;
          </Link>
        </div>
      )}

      {submitError && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
            <div className="text-sm text-red-800 space-y-2">
              <p>{submitError}</p>
              {integrationHint && (
                <Link
                  to="/integrations"
                  className="inline-block font-medium text-red-700 underline hover:text-red-900"
                >
                  Configure telephony credentials in Integrations &rarr;
                </Link>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-end gap-3">
        <Button
          variant="primary"
          leftIcon={<PlayCircle className="h-4 w-4" />}
          onClick={() => startMutation.mutate()}
          isLoading={startMutation.isPending}
          disabled={!canSubmit}
        >
          Start import
        </Button>
      </div>
    </div>
  )
}
