import VoicePlatformConnectGrid from './VoicePlatformConnectGrid'
import type { Integration, IntegrationPlatform } from '../../../../types/api'
import { WizardStepHeader } from './WizardStepHeader'

interface PlatformConnectStepProps {
  integrations: Integration[]
  agentName: string
  onAgentNameChange: (name: string) => void
  selectedPlatform: IntegrationPlatform | null
  onSelectPlatform: (platform: IntegrationPlatform | null) => void
  voiceAiIntegrationId: string
  voiceAiAgentId: string
  onIntegrationChange: (integrationId: string) => void
  onAgentIdChange: (agentId: string) => void
  showNameField?: boolean
  introTitle?: string
  introSubtitle?: string
}

export default function PlatformConnectStep({
  integrations,
  agentName,
  onAgentNameChange,
  selectedPlatform,
  onSelectPlatform,
  voiceAiIntegrationId,
  voiceAiAgentId,
  onIntegrationChange,
  onAgentIdChange,
  showNameField = true,
  introTitle,
  introSubtitle,
}: PlatformConnectStepProps) {
  const title = introTitle ?? (showNameField ? undefined : 'Connect voice platform')
  const subtitle =
    introSubtitle ??
    'Choose a platform, connect your integration, and select the external agent to evaluate.'

  return (
    <div className="space-y-5 max-w-4xl mx-auto">
      {showNameField ? (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
          <input
            type="text"
            required
            value={agentName}
            onChange={(e) => onAgentNameChange(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            placeholder="Customer Support Bot"
          />
        </div>
      ) : title ? (
        <WizardStepHeader title={title} subtitle={subtitle} />
      ) : (
        <p className="text-sm text-gray-600">{subtitle}</p>
      )}

      {showNameField ? (
        <p className="text-sm text-gray-600">{subtitle}</p>
      ) : null}

      <VoicePlatformConnectGrid
        integrations={integrations}
        selectedPlatform={selectedPlatform}
        onSelectPlatform={onSelectPlatform}
        voiceAiIntegrationId={voiceAiIntegrationId}
        voiceAiAgentId={voiceAiAgentId}
        onIntegrationChange={onIntegrationChange}
        onAgentIdChange={onAgentIdChange}
      />
    </div>
  )
}

export function isPlatformConnectValid(
  agentName: string,
  selectedPlatform: IntegrationPlatform | null,
  voiceAiIntegrationId: string,
  voiceAiAgentId: string,
  options?: { requireName?: boolean },
): boolean {
  const requireName = options?.requireName ?? true
  if (requireName && !agentName.trim()) return false
  if (!selectedPlatform) return false
  return Boolean(voiceAiIntegrationId.trim() && voiceAiAgentId.trim())
}
