import { Plus, Save } from 'lucide-react'
import Button from '../../../../components/Button'
import ProviderLogo, { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { useVoicePlayground } from '../context'

export default function VoicesTab() {
  const {
    providerOptionsForVoices,
    customVoices,
    customVoiceProvider,
    customVoiceId,
    customVoiceName,
    customVoiceGender,
    customVoiceAccent,
    customVoiceDescription,
    editingCustomVoiceId,
    canSaveCustomVoice,
    isCreatingCustomVoice,
    isUpdatingCustomVoice,
    isDeletingCustomVoice,
    customVoiceError,
    setCustomVoiceProvider,
    setCustomVoiceId,
    setCustomVoiceName,
    setCustomVoiceGender,
    setCustomVoiceAccent,
    setCustomVoiceDescription,
    createCustomVoice,
    updateCustomVoice,
    startEditingCustomVoice,
    resetCustomVoiceForm,
    setDeleteConfirm,
    deleteCustomVoice,
  } = useVoicePlayground()

  const handleSave = () => {
    if (editingCustomVoiceId) {
      updateCustomVoice()
    } else {
      createCustomVoice()
    }
  }

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl shadow-lg p-6 border border-gray-100">
        <h2 className="text-lg font-semibold text-gray-900 mb-1">Custom Voices</h2>
        <p className="text-sm text-gray-500 mb-5">
          Add provider-specific voice IDs so they can be selected during TTS comparison benchmarks.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Provider</label>
            <select
              value={customVoiceProvider}
              onChange={(e) => setCustomVoiceProvider(e.target.value)}
              disabled={!!editingCustomVoiceId}
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-100"
            >
              <option value="">Select provider...</option>
              {providerOptionsForVoices.map((provider) => (
                <option key={provider} value={provider}>
                  {getProviderInfo(provider).label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Voice ID</label>
            <input
              value={customVoiceId}
              onChange={(e) => setCustomVoiceId(e.target.value)}
              disabled={!!editingCustomVoiceId}
              placeholder="e.g. 21m00Tcm4TlvDq8ikWAM"
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 disabled:bg-gray-100"
            />
            {editingCustomVoiceId && (
              <p className="mt-1 text-xs text-gray-400">Voice ID cannot be changed. Delete and re-create to use a different ID.</p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
            <input
              value={customVoiceName}
              onChange={(e) => setCustomVoiceName(e.target.value)}
              placeholder="e.g. My Sales Voice"
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Gender (optional)
            </label>
            <input
              value={customVoiceGender}
              onChange={(e) => setCustomVoiceGender(e.target.value)}
              placeholder="e.g. Female"
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Accent (optional)
            </label>
            <input
              value={customVoiceAccent}
              onChange={(e) => setCustomVoiceAccent(e.target.value)}
              placeholder="e.g. American"
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Description (optional)
            </label>
            <input
              value={customVoiceDescription}
              onChange={(e) => setCustomVoiceDescription(e.target.value)}
              placeholder="e.g. Cloned from support lead"
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
            />
          </div>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <Button
            variant="primary"
            leftIcon={
              editingCustomVoiceId ? <Save className="w-4 h-4" /> : <Plus className="w-4 h-4" />
            }
            disabled={!canSaveCustomVoice || isCreatingCustomVoice || isUpdatingCustomVoice}
            onClick={handleSave}
          >
            {editingCustomVoiceId ? 'Save Voice' : 'Add Voice'}
          </Button>
          {editingCustomVoiceId && (
            <Button variant="ghost" onClick={resetCustomVoiceForm}>
              Cancel Edit
            </Button>
          )}
        </div>

        {customVoiceError && <p className="mt-3 text-sm text-red-600">{customVoiceError}</p>}
      </div>

      <div className="bg-white rounded-xl shadow-lg p-6 border border-gray-100">
        <h3 className="font-semibold text-gray-900 mb-4">Saved Custom Voices</h3>
        {customVoices.length === 0 ? (
          <p className="text-sm text-gray-500">
            No custom voices yet. Add one above to use it in Playground comparisons.
          </p>
        ) : (
          <div className="space-y-2">
            {customVoices.map((cv) => (
              <div
                key={cv.id}
                className="border border-gray-200 rounded-lg p-3 flex items-center justify-between gap-3"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-gray-900">{cv.name}</span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-primary-100 text-primary-700">
                      Custom
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 inline-flex items-center gap-1.5">
                      <ProviderLogo provider={cv.provider} size="sm" />
                      {getProviderInfo(cv.provider).label}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1 font-mono break-all">
                    Voice ID: {cv.voice_id}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {cv.gender} • {cv.accent}
                  </p>
                  {cv.description && <p className="text-xs text-gray-500 mt-1">{cv.description}</p>}
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <Button variant="ghost" onClick={() => startEditingCustomVoice(cv)}>
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    className="text-red-600 hover:text-red-700"
                    disabled={isDeletingCustomVoice}
                    onClick={() => {
                      setDeleteConfirm({
                        message: `Delete custom voice "${cv.name}" (${cv.voice_id})?`,
                        onConfirm: () => deleteCustomVoice(cv.id),
                      })
                    }}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
