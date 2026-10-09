import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, Copy, Check, AlertTriangle, ChevronDown } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../Button'
import ConfirmModal from '../ConfirmModal'
import { useToast } from '../../hooks/useToast'
import { getApiErrorMessage } from '../../lib/apiErrors'

const ENABLE_PHRASE = 'ENABLE_ALERT_SYNC'

export default function AlertingSyncSettingsCard() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [expanded, setExpanded] = useState(false)
  const [showEnableModal, setShowEnableModal] = useState(false)
  const [phrase, setPhrase] = useState('')
  const [signingSecret, setSigningSecret] = useState('')
  const [copied, setCopied] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['alerting-sync-settings'],
    queryFn: () => apiClient.getAlertingSyncSettings(),
    retry: false,
  })

  const needsSecret =
    Boolean(data?.sync_notification_lifecycle) && !data?.has_pagerduty_webhook_signing_secret

  useEffect(() => {
    if (needsSecret) setExpanded(true)
  }, [needsSecret])

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
    setExpanded(true)
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
        Loading alerting sync…
      </div>
    )
  }

  if (!data) return null

  const statusLabel = data.pagerduty_inbound_ready
    ? 'Enabled'
    : data.sync_notification_lifecycle
      ? 'Enabled — PagerDuty inbound pending'
      : 'Off'

  const statusTone = data.pagerduty_inbound_ready
    ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
    : data.sync_notification_lifecycle
      ? needsSecret
        ? 'bg-amber-50 text-amber-900 border-amber-200'
        : 'bg-blue-50 text-blue-800 border-blue-200'
      : 'bg-gray-50 text-gray-600 border-gray-200'

  return (
    <>
      <ToastContainer />
      <div className="bg-white shadow rounded-lg overflow-hidden border border-gray-200">
        <button
          type="button"
          onClick={() => setExpanded(open => !open)}
          className="w-full px-6 py-4 flex items-center gap-4 text-left hover:bg-gray-50 transition-colors"
          aria-expanded={expanded}
        >
          <Bell className="h-5 w-5 text-amber-600 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-gray-900">Alert channel sync</h2>
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${statusTone}`}>
                {statusLabel}
              </span>
            </div>
            <p className="mt-0.5 text-sm text-gray-500 truncate">
              Keep ack and resolve in sync on Slack, email, and PagerDuty · org admins
            </p>
          </div>
          <ChevronDown
            className={`h-5 w-5 text-gray-400 shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`}
            aria-hidden
          />
        </button>

        {expanded && (
          <div className="px-6 pb-6 pt-2 border-t border-gray-100 space-y-4">
            <div className="flex flex-wrap items-center justify-end gap-3">
              {data.sync_notification_lifecycle ? (
                <Button variant="secondary" onClick={handleDisable} isLoading={saveMutation.isPending}>
                  Turn off
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
                    <p>
                      Outbound sync is on. For PagerDuty ack/resolve back into EfficientAI, add the
                      webhook below and save the signing secret.
                    </p>
                  </div>
                )}

                <div>
                  <div className="text-xs font-semibold text-gray-700 mb-1">
                    PagerDuty inbound webhook
                  </div>
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
                  <p className="text-xs text-gray-500 mt-1">Acknowledged and resolved events.</p>
                </div>

                <div className="pt-2 border-t border-gray-200">
                  <label className="block text-xs font-semibold text-gray-700 mb-2">
                    Signing secret {needsSecret && <span className="text-red-600">*</span>}
                  </label>
                  <input
                    type="password"
                    value={signingSecret}
                    onChange={e => setSigningSecret(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
                    placeholder={
                      data.has_pagerduty_webhook_signing_secret
                        ? 'Enter new secret to replace stored value'
                        : 'Paste from PagerDuty'
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
                      Save secret
                    </Button>
                    {data.pagerduty_inbound_ready && (
                      <span className="text-xs text-emerald-700 font-medium">
                        PagerDuty inbound active
                      </span>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <ConfirmModal
        isOpen={showEnableModal}
        onCancel={() => {
          setShowEnableModal(false)
          setPhrase('')
        }}
        onConfirm={handleEnableConfirm}
        title="Enable alert channel sync?"
        confirmLabel="Enable sync"
        variant="warning"
        isLoading={saveMutation.isPending}
      >
        <div className="space-y-4 text-sm text-gray-600">
          <p>
            Ack and resolve will propagate across Slack, email, and PagerDuty. You can set up
            PagerDuty inbound in this section afterward.
          </p>
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
