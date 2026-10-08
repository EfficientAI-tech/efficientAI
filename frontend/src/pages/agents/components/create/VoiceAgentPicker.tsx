import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Info, RefreshCw } from 'lucide-react'
import AnchoredSelect from '../../../../components/shared/AnchoredSelect'
import { apiClient } from '../../../../lib/api'

interface VoiceAgentPickerProps {
  integrationId: string
  platformLabel: string
  value: string
  onChange: (agentId: string) => void
  agentKind?: 'voice' | 'chat'
  platformLogo?: string | null
}

function FieldInfoTip({ text, label = 'More information' }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative inline-flex shrink-0">
      <button
        type="button"
        className="inline-flex h-5 w-5 items-center justify-center rounded-full text-gray-400 hover:text-gray-600 hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
        aria-label={label}
        aria-expanded={open}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
      >
        <Info className="h-3.5 w-3.5" />
      </button>
      {open ? (
        <div
          role="tooltip"
          className="absolute z-[100] left-1/2 bottom-full mb-1.5 w-72 max-w-[min(18rem,calc(100vw-2rem))] -translate-x-1/2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs leading-relaxed text-gray-700 shadow-lg"
        >
          {text.split('\n\n').map((paragraph, i) => (
            <p key={i} className={i > 0 ? 'mt-2' : undefined}>
              {paragraph}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function chatPlatformHint(platformLabel: string): string {
  if (platformLabel === 'Retell AI') {
    return 'Listed agents are Retell chat-channel only. Voice-only agent IDs will fail when you run chat evals.'
  }
  return `${platformLabel} uses the same assistant for voice and text chat. Pick the agent that handles your chat channel.`
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

  const infoTipText = useMemo(() => {
    const parts: string[] = []
    if (data?.message?.trim()) {
      parts.push(data.message.trim())
    } else if (agentKind === 'chat') {
      parts.push(chatPlatformHint(platformLabel))
    }
    if (data?.truncated) {
      parts.push('Large account — not all agents may be listed. Use manual entry if yours is missing.')
    }
    if (manualEntry && agentKind === 'chat') {
      parts.push(
        platformLabel === 'Retell AI'
          ? 'Paste a Retell chat agent ID (chat channel in Retell — not a voice-only agent ID).'
          : `Paste the ${platformLabel} assistant or agent ID used for text chat.`,
      )
    }
    return parts.length > 0 ? parts.join('\n\n') : null
  }, [data?.message, data?.truncated, agentKind, platformLabel, manualEntry])

  const fieldLabel = agentKind === 'chat' ? 'Chat Agent *' : 'Agent *'
  const labelSuffix = infoTipText ? <FieldInfoTip text={infoTipText} /> : null

  return (
    <div className="space-y-2">
      {showPicker ? (
        <>
          <div className="flex items-end justify-between gap-2">
            <div className="flex-1 min-w-0">
              {errorMessage ? (
                <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2 mb-2">
                  {errorMessage}
                </p>
              ) : null}
              <AnchoredSelect
                label={fieldLabel}
                labelSuffix={labelSuffix}
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
            <p className="text-xs text-amber-800">
              No agents returned — use the info icon next to the label or enter an ID manually.
            </p>
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
          <div className="flex items-center gap-1.5 mb-1.5">
            <label className="text-xs font-medium text-gray-600">{fieldLabel}</label>
            {labelSuffix}
          </div>
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
