import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../../../lib/api'
import { getApiErrorMessage } from '../../../lib/apiErrors'
import Button from '../../../components/Button'
import { useToast } from '../../../hooks/useToast'

type Props = {
  open: boolean
  onClose: () => void
}

export default function ImportPlatformModal({ open, onClose }: Props) {
  const navigate = useNavigate()
  const { showToast, ToastContainer } = useToast()
  const [integrationId, setIntegrationId] = useState('')
  const [windowStart, setWindowStart] = useState('')
  const [windowEnd, setWindowEnd] = useState('')
  const [dataset, setDataset] = useState('')

  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
    enabled: open,
  })

  const voiceIntegrations = useMemo(
    () =>
      integrations.filter((i) =>
        ['elevenlabs', 'vapi', 'retell'].includes((i.platform || '').toLowerCase()),
      ),
    [integrations],
  )

  const createMutation = useMutation({
    mutationFn: () =>
      apiClient.createPlatformCallImport({
        voice_integration_id: integrationId,
        window_start: new Date(windowStart).toISOString(),
        window_end: new Date(windowEnd).toISOString(),
        dataset: dataset || undefined,
      }),
    onSuccess: (result) => {
      showToast('Platform import started', 'success')
      onClose()
      navigate(`/call-imports/${result.id}`)
    },
    onError: (err: unknown) => {
      showToast(getApiErrorMessage(err, 'Failed to start import'), 'error')
    },
  })

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <ToastContainer />
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full p-6 space-y-4">
        <h2 className="text-lg font-semibold text-gray-900">Import from platform</h2>
        <p className="text-sm text-gray-600">
          Pull historical calls from a connected ElevenLabs, Vapi, or Retell account.
        </p>
        <label className="block text-sm">
          <span className="text-gray-700">Credential</span>
          <select
            className="mt-1 w-full border rounded-md px-3 py-2 text-sm"
            value={integrationId}
            onChange={(e) => setIntegrationId(e.target.value)}
          >
            <option value="">Select integration</option>
            {voiceIntegrations.map((i) => (
              <option key={i.id} value={i.id}>
                {(i.name || i.platform) + ` (${i.platform})`}
              </option>
            ))}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm">
            <span className="text-gray-700">Start</span>
            <input
              type="datetime-local"
              className="mt-1 w-full border rounded-md px-3 py-2 text-sm"
              value={windowStart}
              onChange={(e) => setWindowStart(e.target.value)}
            />
          </label>
          <label className="block text-sm">
            <span className="text-gray-700">End</span>
            <input
              type="datetime-local"
              className="mt-1 w-full border rounded-md px-3 py-2 text-sm"
              value={windowEnd}
              onChange={(e) => setWindowEnd(e.target.value)}
            />
          </label>
        </div>
        <label className="block text-sm">
          <span className="text-gray-700">Dataset (optional)</span>
          <input
            className="mt-1 w-full border rounded-md px-3 py-2 text-sm"
            value={dataset}
            onChange={(e) => setDataset(e.target.value)}
          />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!integrationId || !windowStart || !windowEnd}
            isLoading={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Start import
          </Button>
        </div>
      </div>
    </div>
  )
}
