import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { format } from 'date-fns'
import { RefreshCw, Globe, Phone, Eye, Code } from 'lucide-react'
import { VoiceBundle, Integration, IntegrationPlatform } from '../../../types/api'
import { getIntegrationPlatformLabel, getIntegrationPlatformLogo } from '../../../config/providers'
import VoiceBundleDetailCard from './VoiceBundleDetailCard'
import AgentPromptVisualization from './AgentPromptVisualization'
import Button from '../../../components/Button'
import type { AgentTalkMode } from './AgentTalkSidebar'
import { agentProviderPromptTag } from './agentFlowchartUtils'

function stripCodeFences(text: string): string {
  const trimmed = text.trim()
  const full = trimmed.match(/^```[\w]*\n?([\s\S]*?)```\s*$/)
  if (full) return full[1].trim()
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
  silence_hangup_secs?: number
  created_at: string
  updated_at: string
  voice_bundle_id?: string | null
  voice_ai_integration_id?: string | null
  voice_ai_agent_id?: string | null
}

export type AgentDetailTab = 'overview' | 'test_agent' | 'voice_ai_agent'

interface AgentInfoViewProps {
  agent: Agent
  voiceBundles: VoiceBundle[]
  integrations: Integration[]
  activeTab: AgentDetailTab
  onSyncProviderPrompt?: () => void
  isSyncingPrompt?: boolean
  onTalk?: (mode: AgentTalkMode) => void
  onEditVoiceBundle?: (bundleId: string) => void
}

const LANGUAGE_LABELS: Record<string, string> = {
  en: 'English',
  es: 'Spanish',
  fr: 'French',
  de: 'German',
  zh: 'Chinese',
  hi: 'Hindi',
}

const PROSE =
  'prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-ul:text-gray-700 prose-ol:text-gray-700'

function PromptViewToggle({
  view,
  onChange,
}: {
  view: 'text' | 'visualization'
  onChange: (view: 'text' | 'visualization') => void
}) {
  return (
    <div className="flex items-center bg-gray-100 rounded-lg p-0.5 w-fit">
      <button
        type="button"
        onClick={() => onChange('text')}
        className={`inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
          view === 'text' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
        }`}
      >
        <Code className="h-3.5 w-3.5" />
        Text
      </button>
      <button
        type="button"
        onClick={() => onChange('visualization')}
        className={`inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
          view === 'visualization' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
        }`}
      >
        <Eye className="h-3.5 w-3.5" />
        Visualization
      </button>
    </div>
  )
}

export default function AgentInfoView({
  agent,
  voiceBundles,
  integrations,
  activeTab,
  onSyncProviderPrompt,
  isSyncingPrompt,
  onTalk,
  onEditVoiceBundle,
}: AgentInfoViewProps) {
  const navigate = useNavigate()
  const [testPromptView, setTestPromptView] = useState<'text' | 'visualization'>('text')
  const [voiceAiPromptView, setVoiceAiPromptView] = useState<'text' | 'visualization'>('text')

  const linkedBundle = agent.voice_bundle_id
    ? voiceBundles.find((v) => v.id === agent.voice_bundle_id)
    : undefined

  const voiceIntegration = integrations.find((i) => i.id === agent.voice_ai_integration_id)
  const providerLabel = voiceIntegration?.platform
    ? getIntegrationPlatformLabel(voiceIntegration.platform as IntegrationPlatform)
    : 'Provider'

  const providerPromptText = agent.provider_prompt ? stripCodeFences(agent.provider_prompt) : ''

  if (activeTab === 'overview') {
    return (
      <div className="border border-gray-200 rounded-lg p-5 bg-gray-50">
        <h3 className="text-base font-semibold text-gray-900 border-b border-gray-200 pb-2 mb-4">
          General Information
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-4">
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
          <div>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Silence hangup</dt>
            <dd className="mt-1 text-sm text-gray-900">
              {(agent.silence_hangup_secs ?? 15) === 0
                ? 'Disabled'
                : `${agent.silence_hangup_secs ?? 15} seconds`}
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
            <dd className="mt-1 text-sm text-gray-900">
              {format(new Date(agent.created_at), 'MMM d, yyyy HH:mm')}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Updated</dt>
            <dd className="mt-1 text-sm text-gray-900">
              {format(new Date(agent.updated_at), 'MMM d, yyyy HH:mm')}
            </dd>
          </div>
        </div>
      </div>
    )
  }

  if (activeTab === 'test_agent') {
    const canTalk = !!agent.voice_bundle_id
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Test Agent Configuration</h3>
            <p className="text-sm text-gray-500 mt-0.5">
              Voice stack and prompt for EfficientAI test caller, evaluator runs, and playground.
            </p>
          </div>
          {onTalk && (
            <Button
              type="button"
              variant="primary"
              onClick={() => onTalk('test_agent')}
              disabled={!canTalk}
              leftIcon={<Phone className="h-4 w-4" />}
              title={canTalk ? 'Talk to test agent' : 'Configure a voice bundle first'}
            >
              Talk
            </Button>
          )}
        </div>

        <VoiceBundleDetailCard
          bundle={linkedBundle}
          onEdit={
            linkedBundle && onEditVoiceBundle ? () => onEditVoiceBundle(linkedBundle.id) : undefined
          }
          onManageInVoiceBundles={() => navigate('/voicebundles')}
        />

        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <h4 className="text-sm font-semibold text-gray-900">Test Agent Prompt</h4>
            <div className="flex items-center gap-2 flex-wrap">
              <PromptViewToggle view={testPromptView} onChange={setTestPromptView} />
            </div>
          </div>

          {testPromptView === 'text' ? (
            <div className="border border-gray-200 rounded-lg overflow-hidden bg-gray-50">
              <div className="p-5 max-h-[50vh] overflow-y-auto">
                {agent.description ? (
                  <div className={PROSE}>
                    <ReactMarkdown>{agent.description}</ReactMarkdown>
                  </div>
                ) : (
                  <p className="text-sm text-gray-400 italic">No prompt configured. Switch to edit mode to add one.</p>
                )}
              </div>
            </div>
          ) : (
            <AgentPromptVisualization
              agentId={agent.id}
              agentName={agent.name}
              promptContent={agent.description || ''}
              partialNameLabel="System Prompt"
            />
          )}
        </div>
      </div>
    )
  }

  const canTalk = !!(agent.voice_ai_integration_id && agent.voice_ai_agent_id)
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">Voice AI Agent</h3>
          <p className="text-sm text-gray-500 mt-0.5">
            External voice platform agent (Retell, Vapi, ElevenLabs, Smallest).
          </p>
        </div>
        {onTalk && (
          <Button
            type="button"
            variant="primary"
            onClick={() => onTalk('voice_ai_agent')}
            disabled={!canTalk}
            leftIcon={<Phone className="h-4 w-4" />}
            title={canTalk ? 'Talk to voice AI agent' : 'Configure integration and agent ID first'}
          >
            Talk
          </Button>
        )}
      </div>

      <div className="border border-blue-200 rounded-lg p-5 bg-blue-50">
        <h4 className="text-base font-semibold text-gray-900 border-b border-blue-200 pb-2 mb-4">
          Integration
        </h4>
        {agent.voice_ai_integration_id && agent.voice_ai_agent_id ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              {voiceIntegration?.platform && (() => {
                const platform = voiceIntegration.platform as IntegrationPlatform
                const logo = getIntegrationPlatformLogo(platform)
                const label = getIntegrationPlatformLabel(platform)
                return (
                  <>
                    {logo ? <img src={logo} alt={label} className="h-6 w-6 object-contain" /> : null}
                    <span className="text-sm font-medium text-gray-900">{label}</span>
                    {voiceIntegration.name && (
                      <span className="text-sm text-gray-500">({voiceIntegration.name})</span>
                    )}
                  </>
                )
              })()}
            </div>
            <div>
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Provider Agent ID</dt>
              <dd className="text-xs font-mono font-semibold text-primary-600 select-all break-all bg-white/60 px-2.5 py-1.5 rounded border border-gray-200 inline-block">
                {agent.voice_ai_agent_id}
              </dd>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-400 italic">Not configured. Switch to edit mode to link a provider.</p>
        )}
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Globe className="h-4 w-4 text-blue-500" />
            {providerLabel} Prompt
            {agent.provider_prompt_synced_at && (
              <span className="text-xs font-normal text-gray-400">
                · Synced {format(new Date(agent.provider_prompt_synced_at), 'MMM d, HH:mm')}
              </span>
            )}
          </h4>
          <div className="flex items-center gap-2 flex-wrap">
            {onSyncProviderPrompt && agent.voice_ai_integration_id && agent.voice_ai_agent_id && (
              <button
                type="button"
                onClick={onSyncProviderPrompt}
                disabled={isSyncingPrompt}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-blue-700 bg-blue-100 rounded-md hover:bg-blue-200 border border-blue-300 transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`h-3 w-3 ${isSyncingPrompt ? 'animate-spin' : ''}`} />
                {isSyncingPrompt ? 'Syncing…' : 'Sync Now'}
              </button>
            )}
            <PromptViewToggle view={voiceAiPromptView} onChange={setVoiceAiPromptView} />
          </div>
        </div>

        {voiceAiPromptView === 'text' ? (
          <div className="border border-gray-200 rounded-lg overflow-hidden bg-gray-50">
            <div className="p-5 max-h-[50vh] overflow-y-auto">
              {providerPromptText ? (
                <div className={PROSE}>
                  <ReactMarkdown>{providerPromptText}</ReactMarkdown>
                </div>
              ) : agent.voice_ai_integration_id && agent.voice_ai_agent_id ? (
                <p className="text-sm text-gray-500 italic">
                  No {providerLabel.toLowerCase()} prompt synced yet. Click Sync Now to fetch it.
                </p>
              ) : (
                <p className="text-sm text-gray-400 italic">Link a voice AI provider to see the live prompt here.</p>
              )}
            </div>
          </div>
        ) : (
          <AgentPromptVisualization
            agentId={agent.id}
            agentName={agent.name}
            promptContent={providerPromptText}
            linkTag={agentProviderPromptTag(agent.id)}
            partialNameLabel={`${providerLabel} Prompt`}
          />
        )}
      </div>
    </div>
  )
}
