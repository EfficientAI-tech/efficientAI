import { VoiceBundle } from '../../../../types/api'

interface VoiceBundleStepProps {
  voiceBundles: VoiceBundle[]
  value: string
  onChange: (voiceBundleId: string) => void
}

export default function VoiceBundleStep({ voiceBundles, value, onChange }: VoiceBundleStepProps) {
  const activeBundles = voiceBundles.filter((bundle) => bundle.is_active)

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        Select a voice bundle to power the internal test agent path for simulated evaluation runs.
      </p>
      <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
        <label className="block text-sm font-medium text-gray-700 mb-2">Voice Bundle *</label>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
        >
          <option value="">Select a Voice Bundle</option>
          {activeBundles.map((bundle) => (
            <option key={bundle.id} value={bundle.id}>
              {bundle.name}
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
