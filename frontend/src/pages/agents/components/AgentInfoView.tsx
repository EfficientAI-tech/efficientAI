import ReactMarkdown from 'react-markdown'
import { format } from 'date-fns'
import { RefreshCw, Globe } from 'lucide-react'
import { VoiceBundle, Integration } from '../../../types/api'

function stripCodeFences(text: string): string {
  const trimmed = text.trim()
  // Complete fence (opening + closing)
  const full = trimmed.match(/^```[\w]*\n?([\s\S]*?)```\s*$/)
  if (full) return full[1].trim()
  // Opening fence only (no closing — truncated or provider quirk)
  const open = trimmed.match(/^```[\w]*\n?([\s\S]*)$/)
  if (open) return open[1].trim()
  return trimmed
}

interface Agent {
  id: string
  name: string
  phone_number?: string | null
  language: string
  description?: string | null
  provider_prompt?: string | null
  provider_prompt_synced_at?: string | null
  call_type: string
  call_medium: string
  created_at: string
  updated_at: string
  voice_bundle_id?: string | null
  voice_ai_integration_id?: string | null
  voice_ai_agent_id?: string | null
}

interface AgentInfoViewProps {
  agent: Agent
  voiceBundles: VoiceBundle[]
  integrations: Integration[]
  onSyncProviderPrompt?: () => void
  isSyncingPrompt?: boolean
}

const LANGUAGE_LABELS: Record<string, string> = {
  en: 'English',
  es: 'Spanish',
  fr: 'French',
  de: 'German',
  zh: 'Chinese',
  hi: 'Hindi',
}

const PLATFORM_LABELS: Record<string, string> = {
  vapi: 'Vapi',
  retell: 'Retell',
  elevenlabs: 'ElevenLabs',
}

export default function AgentInfoView({
  agent,
  voiceBundles,
  integrations,
  onSyncProviderPrompt,
  isSyncingPrompt,
}: AgentInfoViewProps) {
  const PROSE = 'prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-ul:text-gray-700 prose-ol:text-gray-700'

  const providerLabel = (() => {
    const integration = integrations.find((i) => i.id === agent.voice_ai_integration_id)
    if (integration?.platform) return PLATFORM_LABELS[integration.platform] || integration.platform
    return 'Provider'
  })()

  return (
    <div className="space-y-6">
      {/* ── ROW 1: General Information (full width) ── */}
      <div className="border border-gray-200 rounded-lg p-5 bg-gray-50">
        <h3 className="text-base font-semibold text-gray-900 border-b border-gray-200 pb-2 mb-4">
          General Information
        </h3>
        <div className="grid grid-cols-4 gap-x-6 gap-y-4">
          <div>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Name</dt>
            <dd className="mt-1 text-sm text-gray-900 font-medium">{agent.name}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Language</dt>
            <dd className="mt-1 text-sm text-gray-900">
              {LANGUAGE_LABELS[agent.language] || agent.language}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Call Type</dt>
            <dd className="mt-1 text-sm text-gray-900 capitalize">{agent.call_type}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Call Medium</dt>
            <dd className="mt-1 text-sm text-gray-900">
              {agent.call_medium === 'phone_call' ? 'Phone Call' : 'Web Call'}
            </dd>
          </div>
          {agent.phone_number && (
            <div>
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Phone Number</dt>
              <dd className="mt-1 text-sm text-gray-900">{agent.phone_number}</dd>
            </div>
          )}
          <div>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Created</dt>
            <dd className="mt-1 text-sm text-gray-900">{format(new Date(agent.created_at), 'MMM d, yyyy HH:mm')}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Updated</dt>
            <dd className="mt-1 text-sm text-gray-900">{format(new Date(agent.updated_at), 'MMM d, yyyy HH:mm')}</dd>
          </div>
        </div>

        {/* Voice config summary — two side-by-side cards inside General Info */}
        <div className="mt-5 pt-4 border-t border-gray-200 grid grid-cols-2 gap-6">
          {/* Test Voice Bundle */}
          <div>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">Test Voice Bundle</dt>
            {agent.voice_bundle_id ? (
              <dd className="text-sm font-medium bg-blue-50 text-blue-700 px-3 py-1.5 rounded-md inline-block border border-blue-100">
                {voiceBundles.find((v) => v.id === agent.voice_bundle_id)?.name || agent.voice_bundle_id}
              </dd>
            ) : (
              <dd className="text-sm text-gray-400 italic">Not configured</dd>
            )}
          </div>

          {/* Voice AI Provider + Agent ID */}
          <div>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">{providerLabel} Voice AI</dt>
            {agent.voice_ai_integration_id && agent.voice_ai_agent_id ? (
              <dd>
                <div className="flex items-center gap-2 mb-1.5">
                  {(() => {
                    const integration = integrations.find((i) => i.id === agent.voice_ai_integration_id)
                    if (integration?.platform === 'retell') {
                      return (<><img src="/retellai.png" alt="Retell" className="h-5 w-5 object-contain" /><span className="text-sm font-medium text-gray-900">Retell AI</span></>)
                    } else if (integration?.platform === 'vapi') {
                      return (<><img src="/vapiai.jpg" alt="Vapi" className="h-5 w-5 rounded-full object-contain" /><span className="text-sm font-medium text-gray-900">Vapi AI</span></>)
                    } else if (integration?.platform === 'elevenlabs') {
                      return (<><img src="/elevenlabs.jpg" alt="ElevenLabs" className="h-5 w-5 rounded-full object-contain" /><span className="text-sm font-medium text-gray-900">ElevenLabs</span></>)
                    }
                    return <span className="text-sm text-gray-900">{integration?.name || 'Unknown'}</span>
                  })()}
                </div>
                <div className="text-xs font-mono font-semibold text-primary-600 select-all break-all bg-white/60 px-2.5 py-1.5 rounded border border-gray-200 inline-block">
                  {agent.voice_ai_agent_id}
                </div>
              </dd>
            ) : (
              <dd className="text-sm text-gray-400 italic">Not configured</dd>
            )}
          </div>
        </div>
      </div>

      {/* ── ROW 2: Prompts side by side (perfectly aligned) ── */}
      <div className="grid grid-cols-2 gap-6">
        {/* LEFT: EfficientAI Test Agent Description */}
        <div className="border border-gray-200 rounded-lg overflow-hidden flex flex-col bg-gray-50">
          <div className="flex items-center px-5 py-3 border-b border-gray-200 bg-gray-100/50 flex-shrink-0">
            <h3 className="text-sm font-semibold text-gray-900">
              EfficientAI Test Agent Description
            </h3>
          </div>
          <div className="flex-1 p-5 overflow-y-auto max-h-[50vh]">
            {agent.description ? (
              <div className={PROSE}>
                <ReactMarkdown>{agent.description}</ReactMarkdown>
              </div>
            ) : (
              <span className="text-sm text-gray-400 italic">No description configured.</span>
            )}
          </div>
        </div>

        {/* RIGHT: Provider Prompt */}
        <div className={`border rounded-lg overflow-hidden flex flex-col ${
          agent.voice_ai_integration_id && agent.voice_ai_agent_id
            ? 'border-blue-200 bg-blue-50/20'
            : 'border-gray-200 bg-gray-50/50'
        }`}>
          <div className="flex items-center justify-between px-5 py-3 border-b border-blue-200 bg-blue-50/50 flex-shrink-0">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <Globe className="h-4 w-4 text-blue-500" />
              {providerLabel} Prompt
              {agent.provider_prompt_synced_at && (
                <span className="text-xs font-normal text-gray-400">
                  &middot; Synced {format(new Date(agent.provider_prompt_synced_at), 'MMM d, HH:mm')}
                </span>
              )}
            </h3>
            {onSyncProviderPrompt && agent.voice_ai_integration_id && agent.voice_ai_agent_id && (
              <button
                onClick={onSyncProviderPrompt}
                disabled={isSyncingPrompt}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-blue-700 bg-blue-100 rounded-md hover:bg-blue-200 border border-blue-300 transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`h-3 w-3 ${isSyncingPrompt ? 'animate-spin' : ''}`} />
                {isSyncingPrompt ? 'Syncing...' : 'Sync Now'}
              </button>
            )}
          </div>
          <div className="flex-1 p-5 overflow-y-auto max-h-[50vh]">
            {agent.provider_prompt ? (
              <div className={PROSE}>
                <ReactMarkdown>{stripCodeFences(agent.provider_prompt)}</ReactMarkdown>
              </div>
            ) : agent.voice_ai_integration_id && agent.voice_ai_agent_id ? (
              <p className="text-sm text-gray-500 italic">
                No {providerLabel.toLowerCase()} prompt synced yet. Click "Sync Now" to fetch it.
              </p>
            ) : (
              <p className="text-sm text-gray-400 italic">
                Link a voice AI provider to see the live prompt here.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
