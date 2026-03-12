import { useState } from 'react'
import { X, ChevronDown, ChevronUp } from 'lucide-react'
import ProviderLogo, { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { TTSVoice, TTSProvider } from '../types'

function formatHz(hz: number): string {
  return hz >= 1000 ? `${(hz / 1000).toFixed(1).replace(/\.0$/, '')} kHz` : `${hz} Hz`
}

interface ProviderPanelProps {
  label: string
  color: 'blue' | 'purple'
  providers: TTSProvider[]
  selectedProvider: string
  selectedModel: string
  selectedVoices: TTSVoice[]
  sampleRate: number | null
  onProviderChange: (p: string) => void
  onModelChange: (m: string) => void
  onVoicesChange: (v: TTSVoice[]) => void
  onSampleRateChange: (hz: number | null) => void
}

export default function ProviderPanel({
  label,
  color,
  providers,
  selectedProvider,
  selectedModel,
  selectedVoices,
  sampleRate,
  onProviderChange,
  onModelChange,
  onVoicesChange,
  onSampleRateChange,
}: ProviderPanelProps) {
  const [showAdvanced, setShowAdvanced] = useState(false)
  const providerData = providers.find((p) => p.provider === selectedProvider)
  const models = providerData?.models || []
  const modelVoices = (selectedModel && providerData?.model_voices?.[selectedModel]) || []
  const modelHasBuiltInVoices = modelVoices.some((v) => !v.is_custom)
  const voices = modelVoices.length > 0 && modelHasBuiltInVoices
    ? modelVoices
    : providerData?.voices || modelVoices
  const supportedRates = providerData?.supported_sample_rates || []

  const bgGrad =
    color === 'blue'
      ? 'bg-gradient-to-br from-blue-50 to-sky-50'
      : 'bg-gradient-to-br from-purple-50 to-fuchsia-50'
  const borderColor = color === 'blue' ? 'border-blue-200' : 'border-purple-200'
  const badgeBg = color === 'blue' ? 'bg-blue-600' : 'bg-purple-600'
  const textColor = color === 'blue' ? 'text-blue-900' : 'text-purple-900'
  const chipBg =
    color === 'blue'
      ? 'bg-blue-100 text-blue-800 border-blue-200'
      : 'bg-purple-100 text-purple-800 border-purple-200'
  const ringColor = color === 'blue' ? 'focus:ring-blue-500' : 'focus:ring-purple-500'
  const advancedBorder = color === 'blue' ? 'border-blue-100' : 'border-purple-100'
  const advancedBg = color === 'blue' ? 'bg-blue-50/50' : 'bg-purple-50/50'

  return (
    <div className={`p-5 ${bgGrad} rounded-xl border-2 ${borderColor}`}>
      <div className="flex items-center gap-2 mb-4">
        <span
          className={`w-8 h-8 rounded-full ${badgeBg} text-white flex items-center justify-center text-sm font-bold`}
        >
          {label}
        </span>
        {selectedProvider ? <ProviderLogo provider={selectedProvider} size="md" /> : null}
        <span className={`font-semibold ${textColor}`}>
          {selectedProvider ? getProviderInfo(selectedProvider).label : `Provider ${label}`}
        </span>
      </div>
      <div className="space-y-4">
        {/* Provider select */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">TTS Provider</label>
          <select
            value={selectedProvider}
            onChange={(e) => onProviderChange(e.target.value)}
            className={`w-full px-3 py-2.5 border border-gray-300 rounded-lg ${ringColor} focus:ring-2 bg-white`}
          >
            <option value="">Select provider...</option>
            {providers.map((p) => (
              <option key={p.provider} value={p.provider}>
                {getProviderInfo(p.provider).label}
              </option>
            ))}
          </select>
        </div>

        {/* Model select */}
        {selectedProvider && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">TTS Model</label>
            <select
              value={selectedModel}
              onChange={(e) => onModelChange(e.target.value)}
              className={`w-full px-3 py-2.5 border border-gray-300 rounded-lg ${ringColor} focus:ring-2 bg-white`}
            >
              <option value="">Select model...</option>
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Voice multi-select */}
        {selectedProvider && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Voices</label>
            <select
              value=""
              onChange={(e) => {
                const vid = e.target.value
                const voice = voices.find((v) => v.id === vid)
                if (voice && !selectedVoices.find((v) => v.id === vid)) {
                  onVoicesChange([...selectedVoices, voice])
                }
              }}
              disabled={!selectedProvider}
              className={`w-full px-3 py-2.5 border border-gray-300 rounded-lg ${ringColor} focus:ring-2 disabled:bg-gray-100 bg-white`}
            >
              <option value="">Add a voice...</option>
              {voices
                .filter((v) => !selectedVoices.find((sv) => sv.id === v.id))
                .map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name} {v.is_custom ? '[Custom]' : ''} ({v.gender}, {v.accent})
                  </option>
                ))}
            </select>
            <div className="flex flex-wrap gap-2 mt-2">
              {selectedVoices.map((v) => (
                <div
                  key={v.id}
                  className={`flex items-center gap-1 ${chipBg} text-xs px-2 py-1 rounded-full border`}
                >
                  <span>{v.name}</span>
                  {v.is_custom && (
                    <span className="px-1 py-0.5 rounded bg-white/70 text-[10px] font-semibold">
                      Custom
                    </span>
                  )}
                  <button
                    onClick={() => onVoicesChange(selectedVoices.filter((sv) => sv.id !== v.id))}
                    className="rounded-full p-0.5 hover:opacity-70"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Advanced options (sample rate) */}
        {selectedProvider && supportedRates.length > 0 && (
          <div className={`border ${advancedBorder} rounded-lg overflow-hidden`}>
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className={`w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-gray-500 hover:text-gray-700 ${advancedBg} transition-colors`}
            >
              <span className="flex items-center gap-1.5">
                <svg
                  className="w-3.5 h-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="12" cy="12" r="3" />
                  <path d="M12 1v6m0 6v6m8.66-15l-5.2 3m-6.92 4l-5.2 3M22.66 18l-5.2-3m-6.92-4l-5.2-3" />
                </svg>
                Advanced Options
                {sampleRate && (
                  <span className="ml-1 text-[10px] px-1.5 py-0.5 bg-gray-200 text-gray-600 rounded-full">
                    {formatHz(sampleRate)}
                  </span>
                )}
              </span>
              {showAdvanced ? (
                <ChevronUp className="w-3.5 h-3.5" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5" />
              )}
            </button>
            {showAdvanced && (
              <div className={`px-3 py-3 ${advancedBg} border-t ${advancedBorder}`}>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Output Sample Rate
                  </label>
                  <select
                    value={sampleRate ?? ''}
                    onChange={(e) =>
                      onSampleRateChange(e.target.value ? Number(e.target.value) : null)
                    }
                    className={`w-full px-3 py-2 text-sm border border-gray-300 rounded-lg ${ringColor} focus:ring-2 bg-white`}
                  >
                    <option value="">Default (provider default)</option>
                    {supportedRates.map((hz) => (
                      <option key={hz} value={hz}>
                        {formatHz(hz)}
                      </option>
                    ))}
                  </select>
                  <p className="mt-1 text-[10px] text-gray-400">
                    Frequency at which the TTS audio is generated. Higher rates yield better
                    fidelity.
                  </p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

