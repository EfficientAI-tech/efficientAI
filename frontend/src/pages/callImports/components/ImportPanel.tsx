import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, PlayCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { apiClient } from '../../../lib/api'
import type { CallImport } from '../../../types/api'
import Button from '../../../components/Button'
import TelephonyCredentialPicker, {
  DIRECT_URL_CREDENTIAL,
  credentialSelectionFromState,
  isCredentialSelectionValid,
} from './TelephonyCredentialPicker'

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

  const startMutation = useMutation({
    mutationFn: () => {
      const selection = credentialSelectionFromState(
        selectedProvider,
        selectedIntegrationId,
      )
      return apiClient.startCallImport(callImport.id, selection)
    },
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
    !startMutation.isPending &&
    isCredentialSelectionValid(selectedProvider, selectedIntegrationId)

  const helperText = useMemo(() => {
    if (selectedIntegrationId === DIRECT_URL_CREDENTIAL) {
      return 'Recordings will be downloaded directly from the recording URL column mapped in your schema. Each row must include a valid URL.'
    }
    return 'Pick the telephony provider + credential to use when fetching recordings for this batch. Once started, the per-row workers pick up automatically and progress is reflected on this page.'
  }, [selectedIntegrationId])

  return (
    <div className="bg-white shadow rounded-lg p-6 space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <PlayCircle className="h-5 w-5 text-primary-600" />
          Start import
        </h2>
        <p className="text-sm text-gray-600 mt-1">{helperText}</p>
      </div>

      <TelephonyCredentialPicker
        selectedProvider={selectedProvider}
        selectedIntegrationId={selectedIntegrationId}
        onProviderChange={setSelectedProvider}
        onIntegrationChange={setSelectedIntegrationId}
        disabled={startMutation.isPending}
      />

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
