import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { format } from 'date-fns'
import {
  RefreshCw,
  Globe,
  Phone,
  Eye,
  Code,
  Languages,
  PhoneCall,
  Radio,
  Hash,
} from 'lucide-react'
import ParamSlider from './ParamSlider'
import {
  AGENT_LANGUAGE_LABELS,
  OverviewSection,
  OverviewStatCard,
  OverviewDetailRow,
  OverviewConfigBadge,
  OVERVIEW_NOT_CONFIGURED,
  formatSilenceHangupLabel,
} from './AgentOverviewLayout'
import { VoiceBundle, Integration, IntegrationPlatform, TestAgent } from '../../../types/api'
import { getIntegrationPlatformLabel, getIntegrationPlatformLogo } from '../../../config/providers'
import VoiceBundleDetailCard from './VoiceBundleDetailCard'
import AgentPromptVisualization from './AgentPromptVisualization'
import Button from '../../../components/Button'
import type { AgentTalkMode } from './AgentTalkSidebar'
import { agentProviderPromptTag } from './agentFlowchartUtils'
import TestAgentSubTabNav, { type TestAgentSubTab } from './TestAgentSubTabNav'

function stripCodeFences(text: string): string {
  const trimmed = text.trim()
  const full = trimmed.match(/^```[\w]*\n?([\s\S]*?)```\s*$/)
  if (full) return full[1].trim()
  const open = trimmed.match(/^```[\w]*\n?([\s\S]*)$/)
  if (open) return open[1].trim()
  return trimmed
}

export type AgentDetailTab = 'overview' | 'test_agent' | 'voice_ai_agent'

interface AgentInfoViewProps {
  agent: TestAgent
  voiceBundles: VoiceBundle[]
  integrations: Integration[]
  activeTab: AgentDetailTab
  onSyncProviderPrompt?: () => void
  isSyncingPrompt?: boolean
  onTalk?: (mode: AgentTalkMode) => void
  onEditVoiceBundle?: (bundleId: string) => void
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
  const [testAgentSubTab, setTestAgentSubTab] = useState<TestAgentSubTab>('prompt')

  const linkedBundle = agent.voice_bundle_id
    ? voiceBundles.find((v) => v.id === agent.voice_bundle_id)
    : undefined

  const voiceIntegration = integrations.find((i) => i.id === agent.voice_ai_integration_id)
  const hasPlatformLink = Boolean(agent.voice_ai_integration_id && agent.voice_ai_agent_id)
  const providerLabel = voiceIntegration?.platform
    ? getIntegrationPlatformLabel(voiceIntegration.platform as IntegrationPlatform)
    : 'Production'

  const providerPromptText = agent.provider_prompt ? stripCodeFences(agent.provider_prompt) : ''

  if (activeTab === 'overview') {
    const silenceSecs = agent.silence_hangup_secs ?? 15
    const hasVoiceBundle = Boolean(agent.voice_bundle_id && linkedBundle)
    const testAgentConfigured = hasVoiceBundle && linkedBundle!.is_active !== false
    const voiceAiIntegrationId = agent.voice_ai_integration_id?.trim()
    const voiceAiAgentId = agent.voice_ai_agent_id?.trim()
    const hasVoiceAiIntegration = Boolean(voiceAiIntegrationId && voiceIntegration)
    const hasVoiceAiAgentId = Boolean(voiceAiAgentId)
    const voiceAiConfigured = hasVoiceAiIntegration && hasVoiceAiAgentId

    const voiceBundleLabel = linkedBundle
      ? linkedBundle.name
      : agent.voice_bundle_id
        ? 'Unknown bundle'
        : OVERVIEW_NOT_CONFIGURED

    const voiceAiIntegrationLabel = voiceIntegration
      ? (() => {
          const platformLabel = getIntegrationPlatformLabel(
            voiceIntegration.platform as IntegrationPlatform,
          )
          const name = voiceIntegration.name?.trim()
          return name ? `${name} (${platformLabel})` : platformLabel
        })()
      : voiceAiIntegrationId
        ? 'Unknown integration'
        : OVERVIEW_NOT_CONFIGURED

    return (
      <div className="space-y-5 w-full min-w-0">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 tracking-tight">Overview</h2>
          <p className="text-sm text-gray-500 mt-1">
            Identity, call routing, voice stacks, and session behavior.
          </p>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 items-start">
          <div className="xl:col-span-2 space-y-5 min-w-0">
            <OverviewSection title="Agent profile" description="How this agent is identified and localized.">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <OverviewStatCard icon={Radio} label="Name" value={agent.name} accent="primary" />
                <OverviewStatCard
                  icon={Languages}
                  label="Language"
                  value={AGENT_LANGUAGE_LABELS[agent.language] || agent.language}
                  accent="violet"
                />
              </div>
            </OverviewSection>

            <OverviewSection title="Call setup" description="Medium, direction, and phone number.">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                <OverviewStatCard
                  icon={PhoneCall}
                  label="Call medium"
                  value={agent.call_medium === 'phone_call' ? 'Phone call' : 'Web call'}
                  accent="emerald"
                />
                <OverviewStatCard
                  icon={Phone}
                  label="Call type"
                  value={<span className="capitalize">{agent.call_type}</span>}
                />
                <OverviewStatCard
                  icon={Hash}
                  label="Phone number"
                  value={agent.phone_number?.trim() || OVERVIEW_NOT_CONFIGURED}
                />
              </div>
            </OverviewSection>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <OverviewSection
                title="Live session"
                description="Automatic hangup when the line stays silent."
              >
                <ParamSlider
                  label="End call after silence"
                  helpText={`${formatSilenceHangupLabel(silenceSecs)} · Resets when either side speaks. Set to 0 to disable. Use Edit to change.`}
                  min={0}
                  max={600}
                  step={1}
                  integer
                  value={silenceSecs}
                  onChange={() => {}}
                  disabled
                />
              </OverviewSection>

              <OverviewSection title="Timeline">
                <div className="space-y-1">
                  <OverviewDetailRow
                    label="Created"
                    value={format(new Date(agent.created_at), 'MMM d, yyyy · HH:mm')}
                  />
                  <OverviewDetailRow
                    label="Last updated"
                    value={format(new Date(agent.updated_at), 'MMM d, yyyy · HH:mm')}
                  />
                </div>
              </OverviewSection>
            </div>
          </div>

          <div className="space-y-5 min-w-0">
            <OverviewSection
              title="Test agent (EfficientAI)"
              description="Internal voice stack for playground and evaluator runs."
            >
              <dl>
                <OverviewDetailRow
                  label="Status"
                  value={<OverviewConfigBadge configured={testAgentConfigured} />}
                />
                <OverviewDetailRow label="Voice bundle" value={voiceBundleLabel} />
              </dl>
            </OverviewSection>

            <OverviewSection
              title="Voice AI agent"
              description="External provider agent for side-by-side evaluation."
            >
              <dl>
                <OverviewDetailRow
                  label="Status"
                  value={<OverviewConfigBadge configured={voiceAiConfigured} />}
                />
                <OverviewDetailRow label="Integration" value={voiceAiIntegrationLabel} />
                <OverviewDetailRow
                  label="Provider agent ID"
                  value={
                    hasVoiceAiAgentId ? (
                      <span className="font-mono text-xs font-semibold text-primary-700">
                        {voiceAiAgentId}
                      </span>
                    ) : (
                      OVERVIEW_NOT_CONFIGURED
                    )
                  }
                />
              </dl>
            </OverviewSection>
          </div>
        </div>
      </div>
    )
  }

  if (activeTab === 'test_agent') {
    const canTalk = !!agent.voice_bundle_id
    return (
      <div className="space-y-4">
        <TestAgentSubTabNav value={testAgentSubTab} onChange={setTestAgentSubTab} />

        {testAgentSubTab === 'configuration' && (
          <>
            <div>
              <h3 className="text-base font-semibold text-gray-900">Test Agent Configuration</h3>
              <p className="text-sm text-gray-500 mt-0.5">
                Voice stack for EfficientAI test caller, evaluator runs, and playground.
              </p>
            </div>

            <VoiceBundleDetailCard
              bundle={linkedBundle}
              onEdit={
                linkedBundle && onEditVoiceBundle ? () => onEditVoiceBundle(linkedBundle.id) : undefined
              }
              onManageInVoiceBundles={() => navigate('/voicebundles')}
            />
          </>
        )}

        {testAgentSubTab === 'prompt' && (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div>
                <h3 className="text-base font-semibold text-gray-900">Test Agent Prompt</h3>
                <p className="text-sm text-gray-500 mt-0.5">
                  System prompt used for internal test-agent behavior and evaluation context.
                </p>
              </div>
              <div className="flex items-center gap-2">
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
                    <p className="text-sm text-gray-400 italic">
                      No prompt configured. Use Edit to add one.
                    </p>
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
        )}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">Voice AI Agent</h3>
          <p className="text-sm text-gray-500 mt-0.5">
            {hasPlatformLink
              ? 'External voice platform agent (Retell, Vapi, ElevenLabs, Smallest).'
              : 'Production prompt used to evaluate and generate the test agent.'}
          </p>
        </div>
        {onTalk && hasPlatformLink && (
          <Button
            type="button"
            variant="primary"
            onClick={() => onTalk('voice_ai_agent')}
            leftIcon={<Phone className="h-4 w-4" />}
            title="Talk to voice AI agent"
          >
            Talk
          </Button>
        )}
      </div>

      {hasPlatformLink && (
      <div className="border border-blue-200 rounded-lg p-5 bg-blue-50">
        <h4 className="text-base font-semibold text-gray-900 border-b border-blue-200 pb-2 mb-4">
          Integration
        </h4>
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
      </div>
      )}

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
              ) : hasPlatformLink ? (
                <p className="text-sm text-gray-500 italic">
                  No {providerLabel.toLowerCase()} prompt synced yet. Click Sync Now to fetch it.
                </p>
              ) : (
                <p className="text-sm text-gray-400 italic">
                  No production prompt saved yet. Add one when creating or editing the agent.
                </p>
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
