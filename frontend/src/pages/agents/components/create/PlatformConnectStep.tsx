import { Link } from 'react-router-dom'
import { Integration, IntegrationPlatform } from '../../../../types/api'
import { getIntegrationPlatformLabel, getIntegrationPlatformLogo } from '../../../../config/providers'

const PLATFORM_OPTIONS: IntegrationPlatform[] = [
  IntegrationPlatform.VAPI,
  IntegrationPlatform.RETELL,
  IntegrationPlatform.ELEVENLABS,
  IntegrationPlatform.SMALLEST,
]

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
}: PlatformConnectStepProps) {
  const activeIntegrations = integrations.filter((integration) => integration.is_active)

  const integrationsForPlatform = (platform: IntegrationPlatform) =>
    activeIntegrations.filter((integration) => integration.platform === platform)

  return (
    <div className="space-y-4">
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

      <p className="text-sm text-gray-600">
        Choose a voice AI platform and connect it with your integration credentials and external Agent ID.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {PLATFORM_OPTIONS.map((platform) => {
          const logo = getIntegrationPlatformLogo(platform)
          const label = getIntegrationPlatformLabel(platform)
          const isSelected = selectedPlatform === platform
          const platformIntegrations = integrationsForPlatform(platform)

          return (
            <div
              key={platform}
              className={`rounded-xl border-2 p-4 ${
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
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">Integration *</label>
                        <select
                          value={voiceAiIntegrationId}
                          onChange={(e) => onIntegrationChange(e.target.value)}
                          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500"
                        >
                          <option value="">Select integration</option>
                          {platformIntegrations.map((integration) => (
                            <option key={integration.id} value={integration.id}>
                              {integration.name || label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">Agent ID *</label>
                        <input
                          type="text"
                          value={voiceAiAgentId}
                          onChange={(e) => onAgentIdChange(e.target.value)}
                          placeholder={`Enter ${label} agent ID`}
                          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500 font-mono"
                        />
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function isPlatformConnectValid(
  agentName: string,
  selectedPlatform: IntegrationPlatform | null,
  voiceAiIntegrationId: string,
  voiceAiAgentId: string,
): boolean {
  if (!agentName.trim()) return false
  if (!selectedPlatform) return false
  return Boolean(voiceAiIntegrationId.trim() && voiceAiAgentId.trim())
}
