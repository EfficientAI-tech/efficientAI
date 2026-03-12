import { Plus, Save, X } from 'lucide-react'
import { useState } from 'react'
import Button from '../../../../components/Button'
import ProviderLogo, { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { useVoicePlayground } from '../context'

export default function VoicesTab() {
  const [showVoiceModal, setShowVoiceModal] = useState(false)
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

  const openAddVoiceModal = () => {
    resetCustomVoiceForm()
    setShowVoiceModal(true)
  }

  const closeVoiceModal = () => {
    resetCustomVoiceForm()
    setShowVoiceModal(false)
  }

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl shadow-lg p-6 border border-gray-100">
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <h3 className="font-semibold text-gray-900">Saved Custom Voices</h3>
            <p className="text-sm text-gray-500 mt-1">
              Manage provider-specific voices used during TTS comparison benchmarks.
            </p>
          </div>
          <Button
            variant="primary"
            leftIcon={<Plus className="w-4 h-4" />}
            onClick={openAddVoiceModal}
          >
            Add Custom Voice
          </Button>
        </div>
        {customVoices.length === 0 ? (
          <p className="text-sm text-gray-500">
            No custom voices yet. Click <span className="font-medium">Add Custom Voice</span> to create one.
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
                  <Button
                    variant="ghost"
                    onClick={() => {
                      startEditingCustomVoice(cv)
                      setShowVoiceModal(true)
                    }}
                  >
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

      {/* Add/Edit Custom Voice Modal */}
      {showVoiceModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={closeVoiceModal}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-gray-900">
                  {editingCustomVoiceId ? 'Edit Custom Voice' : 'Add Custom Voice'}
                </h2>
                <button
                  onClick={closeVoiceModal}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

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
                    placeholder="e.g. 21m00Tcm4TlvDq8ikWAM"
                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                  />
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

              {customVoiceError && <p className="mt-3 text-sm text-red-600">{customVoiceError}</p>}

              <div className="mt-6 flex justify-end gap-2">
                <Button variant="ghost" onClick={closeVoiceModal}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  leftIcon={editingCustomVoiceId ? <Save className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
                  disabled={!canSaveCustomVoice || isCreatingCustomVoice || isUpdatingCustomVoice}
                  isLoading={isCreatingCustomVoice || isUpdatingCustomVoice}
                  onClick={handleSave}
                >
                  {editingCustomVoiceId ? 'Save Voice' : 'Add Voice'}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
