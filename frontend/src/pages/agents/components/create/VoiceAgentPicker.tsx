import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { apiClient } from '../../../../lib/api'

interface VoiceAgentPickerProps {
  integrationId: string
  platformLabel: string
  value: string
  onChange: (agentId: string) => void
}

export default function VoiceAgentPicker({
  integrationId,
  platformLabel,
  value,
  onChange,
}: VoiceAgentPickerProps) {
  const queryClient = useQueryClient()
  const [manualEntry, setManualEntry] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['integration-voice-agents', integrationId],
    queryFn: () => apiClient.listIntegrationVoiceAgents(integrationId),
    enabled: Boolean(integrationId) && !manualEntry,
    staleTime: 60_000,
  })

  useEffect(() => {
    setManualEntry(false)
  }, [integrationId])

  useEffect(() => {
    if (data && !data.list_supported) {
      setManualEntry(true)
    }
  }, [data?.list_supported, integrationId])

  const handleRefresh = async () => {
    if (!integrationId) return
    setIsRefreshing(true)
    try {
      const fresh = await apiClient.listIntegrationVoiceAgents(integrationId, { refresh: true })
      queryClient.setQueryData(['integration-voice-agents', integrationId], fresh)
    } finally {
      setIsRefreshing(false)
    }
  }

  const errorMessage =
    isError && error
      ? (error as { response?: { data?: { detail?: string } }; message?: string }).response?.data
          ?.detail ||
        (error as { message?: string }).message ||
        'Failed to load agents'
      : null

  const showPicker = Boolean(integrationId) && !manualEntry && data?.list_supported !== false
  const agents = data?.agents ?? []
  const busy = isLoading || isFetching || isRefreshing

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <label className="block text-xs font-medium text-gray-600">Agent *</label>
        {showPicker ? (
          <button
            type="button"
            onClick={handleRefresh}
            disabled={busy}
            className="inline-flex items-center gap-1 text-xs text-gray-600 hover:text-gray-900 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        ) : null}
      </div>

      {showPicker ? (
        <>
          {errorMessage ? (
            <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
              {errorMessage}
            </p>
          ) : null}
          {data?.message ? (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
              {data.message}
            </p>
          ) : null}
          {data?.truncated ? (
            <p className="text-xs text-gray-600">
              Large account — not all agents may be listed. Use manual entry if yours is missing.
            </p>
          ) : null}
          <select
            value={value}
            onChange={(e) => onChange(e.target.value)}
            disabled={busy || Boolean(errorMessage)}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50"
          >
            <option value="">{busy ? 'Loading agents…' : 'Select agent'}</option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name} ({agent.id})
              </option>
            ))}
          </select>
          {!busy && agents.length === 0 && !errorMessage ? (
            <p className="text-xs text-gray-500">No agents returned for this integration.</p>
          ) : null}
          <button
            type="button"
            onClick={() => {
              setManualEntry(true)
              onChange('')
            }}
            className="text-xs text-primary-700 hover:text-primary-900 underline"
          >
            Enter agent ID manually
          </button>
        </>
      ) : (
        <>
          {data?.message ? (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
              {data.message}
            </p>
          ) : null}
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={`Enter ${platformLabel} agent ID`}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500 font-mono"
          />
          {data?.list_supported !== false ? (
            <button
              type="button"
              onClick={() => setManualEntry(false)}
              className="text-xs text-primary-700 hover:text-primary-900 underline"
            >
              Choose from list
            </button>
          ) : null}
        </>
      )}
    </div>
  )
}
