import { VoiceBundle } from '../../../../types/api'

interface VoiceBundleStepProps {
  voiceBundles: VoiceBundle[]
  value: string
  onChange: (voiceBundleId: string) => void
  /** Chat agents only need the bundle's LLM credentials in v0 (not STT/TTS). */
  mode?: 'voice' | 'chat'
}

function bundleLlmLabel(bundle: VoiceBundle): string {
  const provider = bundle.llm_provider || 'llm'
  const model = bundle.llm_model || 'default'
  return `${bundle.name} — ${provider} / ${model}`
}

export default function VoiceBundleStep({
  voiceBundles,
  value,
  onChange,
  mode = 'voice',
}: VoiceBundleStepProps) {
  const activeBundles = voiceBundles.filter((bundle) => bundle.is_active)
  const isChat = mode === 'chat'

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        {isChat
          ? 'v0 uses an existing voice bundle only for LLM provider, model, and API keys. STT/TTS on the bundle are ignored in text simulation. A dedicated “chat LLM only” picker is planned.'
          : 'Select a voice bundle to power the internal test agent path for simulated evaluation runs.'}
      </p>
      <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {isChat ? 'LLM configuration (via bundle) *' : 'Voice Bundle *'}
        </label>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
        >
          <option value="">{isChat ? 'Select LLM bundle' : 'Select a Voice Bundle'}</option>
          {activeBundles.map((bundle) => (
            <option key={bundle.id} value={bundle.id}>
              {isChat ? bundleLlmLabel(bundle) : bundle.name}
            </option>
          ))}
        </select>
        {activeBundles.length === 0 && (
          <p className="mt-1 text-xs text-gray-500">No active voice bundles available.</p>
        )}
      </div>
    </div>
  )
}
