import { Link } from 'react-router-dom'
import { Integration, IntegrationPlatform } from '../../../../types/api'
import { getIntegrationPlatformLabel, getIntegrationPlatformLogo } from '../../../../config/providers'
import AnchoredSelect from '../../../../components/shared/AnchoredSelect'
import VoiceAgentPicker from './VoiceAgentPicker'

export const VOICE_PLATFORM_OPTIONS: IntegrationPlatform[] = [
  IntegrationPlatform.VAPI,
  IntegrationPlatform.RETELL,
  IntegrationPlatform.ELEVENLABS,
  IntegrationPlatform.SMALLEST,
]

export interface VoicePlatformConnectGridProps {
  integrations: Integration[]
  selectedPlatform: IntegrationPlatform | null
  onSelectPlatform: (platform: IntegrationPlatform | null) => void
  voiceAiIntegrationId: string
  voiceAiAgentId: string
  onIntegrationChange: (integrationId: string) => void
  onAgentIdChange: (agentId: string) => void
  platformOptions?: IntegrationPlatform[]
  remoteAgentKind?: 'voice' | 'chat'
}

export default function VoicePlatformConnectGrid({
  integrations,
  selectedPlatform,
  onSelectPlatform,
  voiceAiIntegrationId,
  voiceAiAgentId,
  onIntegrationChange,
  onAgentIdChange,
  platformOptions = VOICE_PLATFORM_OPTIONS,
  remoteAgentKind = 'voice',
}: VoicePlatformConnectGridProps) {
  const activeIntegrations = integrations.filter((integration) => integration.is_active)

  const integrationsForPlatform = (platform: IntegrationPlatform) =>
    activeIntegrations.filter((integration) => integration.platform === platform)

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {platformOptions.map((platform) => {
        const logo = getIntegrationPlatformLogo(platform)
        const label = getIntegrationPlatformLabel(platform)
        const isSelected = selectedPlatform === platform
        const platformIntegrations = integrationsForPlatform(platform)

        return (
          <div
            key={platform}
            className={`rounded-xl border-2 p-4 transition-colors ${
              isSelected ? 'border-primary-600 bg-primary-50' : 'border-gray-200 bg-white'
            }`}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 min-w-0">
                {logo ? (
                  <img src={logo} alt={label} className="h-8 w-8 object-contain shrink-0" />
                ) : null}
                <span className="text-sm font-semibold text-gray-900">{label}</span>
              </div>
              <button
                type="button"
                onClick={() => onSelectPlatform(isSelected ? null : platform)}
                className={`shrink-0 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                  isSelected
                    ? 'bg-primary-600 text-white border-primary-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                {isSelected ? 'Connected' : 'Connect'}
              </button>
            </div>

            {isSelected && (
              <div className="mt-4 space-y-3 pt-3 border-t border-primary-200">
                {platformIntegrations.length === 0 ? (
                  <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
                    No active {label} integration found.{' '}
                    <Link to="/integrations" className="underline font-medium">
                      Add integration
                    </Link>
                  </p>
                ) : (
                  <>
                    <AnchoredSelect
                      label="Integration *"
                      value={voiceAiIntegrationId}
                      options={platformIntegrations.map((integration) => ({
                        value: integration.id,
                        label: integration.name || label,
                        iconUrl: logo,
                      }))}
                      placeholder="Select integration"
                      onChange={onIntegrationChange}
                    />
                    {voiceAiIntegrationId ? (
                      <VoiceAgentPicker
                        integrationId={voiceAiIntegrationId}
                        platformLabel={label}
                        value={voiceAiAgentId}
                        onChange={onAgentIdChange}
                        agentKind={
                          remoteAgentKind === 'chat' && platform === IntegrationPlatform.RETELL
                            ? 'chat'
                            : 'voice'
                        }
                      />
                    ) : null}
                  </>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
