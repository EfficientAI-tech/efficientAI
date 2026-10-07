import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, Copy, Check, AlertTriangle } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../Button'
import ConfirmModal from '../ConfirmModal'
import { useToast } from '../../hooks/useToast'
import { getApiErrorMessage } from '../../lib/apiErrors'

const ENABLE_PHRASE = 'ENABLE_ALERT_SYNC'

export default function AlertingSyncSettingsCard() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showEnableModal, setShowEnableModal] = useState(false)
  const [phrase, setPhrase] = useState('')
  const [signingSecret, setSigningSecret] = useState('')
  const [copied, setCopied] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['alerting-sync-settings'],
    queryFn: () => apiClient.getAlertingSyncSettings(),
    retry: false,
  })

  const saveMutation = useMutation({
    mutationFn: (payload: Parameters<typeof apiClient.updateAlertingSyncSettings>[0]) =>
      apiClient.updateAlertingSyncSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerting-sync-settings'] })
      setShowEnableModal(false)
      setPhrase('')
      setSigningSecret('')
      showToast('Alerting sync settings saved', 'success')
    },
    onError: (err: unknown) =>
      showToast(getApiErrorMessage(err, 'Failed to save alerting sync settings'), 'error'),
  })

  const handleDisable = () => {
    saveMutation.mutate({ sync_notification_lifecycle: false })
  }

  const handleEnableConfirm = () => {
    if (phrase.trim() !== ENABLE_PHRASE) {
      showToast(`Type ${ENABLE_PHRASE} exactly to enable sync`, 'error')
      return
    }
    saveMutation.mutate({
      sync_notification_lifecycle: true,
      confirm_enable: true,
      confirmation_phrase: phrase,
    })
  }

  const copyWebhook = async () => {
    if (!data?.pagerduty_webhook_url) return
    await navigator.clipboard.writeText(data.pagerduty_webhook_url)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (isLoading) {
    return (
      <div className="bg-white shadow rounded-lg p-6 text-sm text-gray-500">
        Loading alerting integration settings…
      </div>
    )
  }

  if (!data) return null

  const needsSecret =
    data.sync_notification_lifecycle && !data.has_pagerduty_webhook_signing_secret

  return (
    <>
      <ToastContainer />
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Bell className="h-5 w-5" />
            Alert notification sync
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Keep ack/resolve in sync across channels. PagerDuty inbound needs the signing secret.
          </p>
        </div>
        <div className="p-6 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-gray-900">
                {data.pagerduty_inbound_ready
                  ? 'Sync enabled (outbound + inbound)'
                  : data.sync_notification_lifecycle
                    ? 'Sync enabled (outbound only)'
                    : 'Sync disabled'}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">Org admins only</div>
            </div>
            {data.sync_notification_lifecycle ? (
              <Button variant="secondary" onClick={handleDisable} isLoading={saveMutation.isPending}>
                Turn off sync
              </Button>
            ) : (
              <Button variant="primary" onClick={() => setShowEnableModal(true)}>
                Enable sync
              </Button>
            )}
          </div>

          {data.sync_notification_lifecycle && data.pagerduty_webhook_url && (
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-4">
              {needsSecret && (
                <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                  <p>Add the webhook in PagerDuty, then save the signing secret below.</p>
                </div>
              )}

              <div>
                <div className="text-xs font-semibold text-gray-700 mb-1">Webhook URL</div>
                <div className="flex gap-2">
                  <code className="flex-1 text-xs break-all bg-white border border-gray-200 rounded-lg px-2 py-2">
                    {data.pagerduty_webhook_url}
                  </code>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={copyWebhook}
                    leftIcon={copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  >
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  PagerDuty webhook: ack + resolved events.
                </p>
              </div>

              <div className="pt-2 border-t border-gray-200">
                <div className="text-xs font-semibold text-gray-700 mb-2">
                  Signing secret <span className="text-red-600">*</span>
                </div>
                <input
                  type="password"
                  value={signingSecret}
                  onChange={e => setSigningSecret(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
                  placeholder={
                    data.has_pagerduty_webhook_signing_secret
                      ? 'Enter new secret to replace stored value'
                      : 'Paste signing secret from PagerDuty'
                  }
                  autoComplete="off"
                />
                <div className="mt-2 flex items-center gap-3">
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={!signingSecret.trim()}
                    isLoading={saveMutation.isPending}
                    onClick={() =>
                      saveMutation.mutate({
                        sync_notification_lifecycle: true,
                        pagerduty_webhook_signing_secret: signingSecret.trim(),
                      })
                    }
                  >
                    Save signing secret
                  </Button>
                  {data.pagerduty_inbound_ready && (
                    <span className="text-xs text-emerald-700 font-medium">Inbound sync active</span>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <ConfirmModal
        isOpen={showEnableModal}
        onCancel={() => {
          setShowEnableModal(false)
          setPhrase('')
        }}
        onConfirm={handleEnableConfirm}
        title="Enable alert notification sync?"
        confirmLabel="Enable sync"
        variant="warning"
        isLoading={saveMutation.isPending}
      >
        <div className="space-y-4 text-sm text-gray-600">
          <p>Enables cross-channel ack/resolve. You’ll set up the PagerDuty webhook next.</p>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Type <span className="font-mono text-gray-900">{ENABLE_PHRASE}</span> to confirm
            </label>
            <input
              value={phrase}
              onChange={e => setPhrase(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              autoComplete="off"
            />
          </div>
        </div>
      </ConfirmModal>
    </>
  )
}
