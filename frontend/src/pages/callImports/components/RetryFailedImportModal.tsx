import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import Button from '../../../components/Button'
import type { CallImport } from '../../../types/api'
import TelephonyCredentialPicker, {
  DIRECT_URL_CREDENTIAL,
  credentialSelectionFromState,
  isCredentialSelectionValid,
} from './TelephonyCredentialPicker'

interface RetryFailedImportModalProps {
  isOpen: boolean
  failedCount: number
  callImport: CallImport | undefined
  isLoading?: boolean
  errorMessage?: string | null
  onConfirm: (selection: {
    provider: string | null
    telephonyIntegrationId: string | null
  }) => void
  onCancel: () => void
}

function initialSelection(callImport: CallImport | undefined) {
  if (callImport?.telephony_integration_id && callImport.provider) {
    return {
      provider: callImport.provider,
      integrationId: callImport.telephony_integration_id,
    }
  }
  if (!callImport?.telephony_integration_id && !callImport?.provider) {
    return { provider: '', integrationId: DIRECT_URL_CREDENTIAL }
  }
  return { provider: callImport?.provider || '', integrationId: '' }
}

export default function RetryFailedImportModal({
  isOpen,
  failedCount,
  callImport,
  isLoading = false,
  errorMessage = null,
  onConfirm,
  onCancel,
}: RetryFailedImportModalProps) {
  const [selectedProvider, setSelectedProvider] = useState('')
  const [selectedIntegrationId, setSelectedIntegrationId] = useState('')

  useEffect(() => {
    if (!isOpen) return
    const initial = initialSelection(callImport)
    setSelectedProvider(initial.provider)
    setSelectedIntegrationId(initial.integrationId)
  }, [isOpen, callImport?.id, callImport?.provider, callImport?.telephony_integration_id])

  const canSubmit = isCredentialSelectionValid(
    selectedProvider,
    selectedIntegrationId,
  )

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        <div
          className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
          onClick={onCancel}
        />

        <div className="relative bg-white rounded-2xl shadow-xl max-w-lg w-full p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2.5 rounded-full bg-[#fef7e0]">
              <AlertTriangle className="w-5 h-5 text-[#f29900]" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900">
              Retry {failedCount} failed import row
              {failedCount === 1 ? '' : 's'}
            </h3>
          </div>

          <div className="space-y-4 mb-6">
            <p className="text-sm text-gray-600">
              Choose how recordings should be fetched for this retry pass. You
              can switch credentials or use direct recording URLs from the CSV.
            </p>

            <TelephonyCredentialPicker
              selectedProvider={selectedProvider}
              selectedIntegrationId={selectedIntegrationId}
              onProviderChange={setSelectedProvider}
              onIntegrationChange={setSelectedIntegrationId}
              disabled={isLoading}
              compact
            />

            {errorMessage && (
              <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-800">
                {errorMessage}
              </div>
            )}
          </div>

          <div className="flex justify-end gap-3">
            <Button variant="ghost" onClick={onCancel} disabled={isLoading}>
              Cancel
            </Button>
            <button
              onClick={() =>
                onConfirm(credentialSelectionFromState(
                  selectedProvider,
                  selectedIntegrationId,
                ))
              }
              disabled={isLoading || !canSubmit}
              className="px-4 py-2 rounded-full font-semibold transition-colors disabled:opacity-50 bg-[#fef7e0] hover:bg-[#feefc3] text-[#e37400] border-0"
            >
              {isLoading ? 'Retrying…' : `Retry ${failedCount} failed row${failedCount === 1 ? '' : 's'}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
