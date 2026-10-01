import { Link } from 'react-router-dom'
import { Integration, IntegrationPlatform } from '../../../../types/api'
import {
  getIntegrationPlatformLabel,
  getIntegrationPlatformLogo,
} from '../../../../config/providers'
import { NATIVE_PROVIDER_TEXT_CHAT_PLATFORMS } from '../../../../lib/chatConnectionCapabilities'
import AnchoredSelect from '../../../../components/shared/AnchoredSelect'
import VoiceAgentPicker from '../create/VoiceAgentPicker'

interface Props {
  integrations: Integration[]
  selectedPlatform: IntegrationPlatform | null
  onSelectPlatform: (platform: IntegrationPlatform | null) => void
  voiceAiIntegrationId: string
  voiceAiAgentId: string
  onIntegrationChange: (integrationId: string) => void
  onAgentIdChange: (agentId: string) => void
}

export default function ChatPlatformConnectionFields({
  integrations,
  selectedPlatform,
  onSelectPlatform,
  voiceAiIntegrationId,
  voiceAiAgentId,
  onIntegrationChange,
  onAgentIdChange,
}: Props) {
  const activeIntegrations = integrations.filter((i) => i.is_active)

  const integrationsForPlatform = (platform: IntegrationPlatform) =>
    activeIntegrations.filter((i) => i.platform === platform)

  const platformLabel = selectedPlatform ? getIntegrationPlatformLabel(selectedPlatform) : ''

  return (
    <div className="space-y-5">
      <div>
        <span className="block text-sm font-medium text-gray-700 mb-2">Platform</span>
        <div className="flex flex-wrap gap-2">
          {NATIVE_PROVIDER_TEXT_CHAT_PLATFORMS.map((platform) => {
            const logo = getIntegrationPlatformLogo(platform)
            const label = getIntegrationPlatformLabel(platform)
            const selected = selectedPlatform === platform
            return (
              <button
                key={platform}
                type="button"
                onClick={() => onSelectPlatform(selected ? null : platform)}
                className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                  selected
                    ? 'border-primary-600 bg-primary-50 text-primary-900 ring-1 ring-primary-200'
                    : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50'
                }`}
              >
                {logo ? <img src={logo} alt="" className="h-5 w-5 object-contain" /> : null}
                {label}
              </button>
            )
          })}
        </div>
      </div>

      {selectedPlatform ? (
        <div className="space-y-4 pt-1 border-t border-gray-100">
          {integrationsForPlatform(selectedPlatform).length === 0 ? (
            <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              No active {platformLabel} integration.{' '}
              <Link to="/integrations" className="font-medium underline">
                Add integration
              </Link>
            </p>
          ) : (
            <>
              <AnchoredSelect
                label="Integration"
                value={voiceAiIntegrationId}
                options={integrationsForPlatform(selectedPlatform).map((integration) => ({
                  value: integration.id,
                  label: integration.name || platformLabel,
                  iconUrl: getIntegrationPlatformLogo(selectedPlatform),
                }))}
                placeholder="Select integration"
                onChange={onIntegrationChange}
              />
              {voiceAiIntegrationId ? (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Agent ID</label>
                  <VoiceAgentPicker
                    integrationId={voiceAiIntegrationId}
                    platformLabel={platformLabel}
                    platformLogo={getIntegrationPlatformLogo(selectedPlatform)}
                    value={voiceAiAgentId}
                    onChange={onAgentIdChange}
                    agentKind="chat"
                  />
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}
