import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import AnchoredSelect from '../../../../components/shared/AnchoredSelect'
import { apiClient } from '../../../../lib/api'

interface VoiceAgentPickerProps {
  integrationId: string
  platformLabel: string
  value: string
  onChange: (agentId: string) => void
  /** Retell text chat needs chat-channel agent IDs, not voice agents. */
  agentKind?: 'voice' | 'chat'
  platformLogo?: string | null
}

export default function VoiceAgentPicker({
  integrationId,
  platformLabel,
  value,
  onChange,
  agentKind = 'voice',
  platformLogo = null,
}: VoiceAgentPickerProps) {
  const queryClient = useQueryClient()
  const [manualEntry, setManualEntry] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['integration-voice-agents', integrationId, agentKind],
    queryFn: () => apiClient.listIntegrationVoiceAgents(integrationId, { agentKind }),
    enabled: Boolean(integrationId),
    staleTime: 60_000,
  })

  useEffect(() => {
    setManualEntry(false)
  }, [integrationId, agentKind])

  useEffect(() => {
    if (data && !data.list_supported) {
      setManualEntry(true)
    }
  }, [data?.list_supported, integrationId])

  const handleRefresh = async () => {
    if (!integrationId) return
    setIsRefreshing(true)
    try {
      const fresh = await apiClient.listIntegrationVoiceAgents(integrationId, {
        refresh: true,
        agentKind,
      })
      queryClient.setQueryData(['integration-voice-agents', integrationId, agentKind], fresh)
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
      {showPicker ? (
        <>
          <div className="flex items-end justify-between gap-2">
            <div className="flex-1 min-w-0">
          {errorMessage ? (
            <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
              {errorMessage}
            </p>
          ) : null}
          {data?.message ? (
            <p
              className={`text-xs rounded-md px-3 py-2 ${
                agents.length === 0
                  ? 'text-amber-800 bg-amber-50 border border-amber-200'
                  : 'text-gray-600 bg-gray-50 border border-gray-200'
              }`}
            >
              {data.message}
            </p>
          ) : null}
          {agentKind === 'chat' && agents.length > 0 && !data?.message ? (
            <p className="text-xs text-gray-500">
              Listed agents are Retell chat-channel only. Voice-only IDs fail at runtime.
            </p>
          ) : null}
          {data?.truncated ? (
            <p className="text-xs text-gray-600">
              Large account — not all agents may be listed. Use manual entry if yours is missing.
            </p>
          ) : null}
              <AnchoredSelect
                label={agentKind === 'chat' ? 'Chat Agent *' : 'Agent *'}
                value={value}
                options={agents.map((agent) => ({
                  value: agent.id,
                  label: `${agent.name} (${agent.id})`,
                  iconUrl: platformLogo,
                }))}
                placeholder={busy ? 'Loading agents…' : 'Select agent'}
                disabled={busy || Boolean(errorMessage)}
                onChange={onChange}
                maxMenuHeight={280}
              />
            </div>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={busy}
              className="mb-0.5 inline-flex shrink-0 items-center gap-1 text-xs text-gray-600 hover:text-gray-900 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
          {!busy && agents.length === 0 && !errorMessage ? (
            <p className="text-xs text-gray-500">No agents returned for this integration.</p>
          ) : null}
          <button
            type="button"
            onClick={() => setManualEntry(true)}
            className="text-xs text-primary-700 hover:text-primary-900 underline"
          >
            Enter agent ID manually
          </button>
        </>
      ) : (
        <>
          <label className="block text-xs font-medium text-gray-600">
            {agentKind === 'chat' ? 'Chat Agent *' : 'Agent *'}
          </label>
          {data?.message ? (
            <p className="text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded-md px-3 py-2">
              {data.message}
            </p>
          ) : null}
          {agentKind === 'chat' ? (
            <p className="text-xs text-gray-500">
              Paste the Retell <span className="font-medium">chat</span> agent ID (from the Retell
              dashboard or chat agent list).
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
