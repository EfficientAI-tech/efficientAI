import { Mic, History, Headphones, RotateCcw, X } from 'lucide-react'
import Button from '../../../components/Button'
import { VoicePlaygroundProvider, useVoicePlayground } from './context'
import { PlaygroundTab, VoicesTab, SimulationsTab } from './components'
import { useWalkthroughSectionState } from '../../../context/WalkthroughContext'
import WalkthroughToggleButton from '../../../components/walkthrough/WalkthroughToggleButton'

function VoicePlaygroundContent() {
  const {
    activeTab,
    setActiveTab,
    step,
    customVoices,
    pastComparisons,
    setViewingPastId,
    resetPlayground,
    deleteConfirm,
    setDeleteConfirm,
  } = useVoicePlayground()

  useWalkthroughSectionState(
    'voice-playground',
    { activeTab, step },
    [activeTab, step]
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
            <Mic className="w-8 h-8 text-primary-600" />
            Voice Playground
          </h1>
          <p className="mt-2 text-sm text-gray-600">
            A/B test TTS providers &mdash; compare voice quality with real synthesis, blind tests,
            and automated evaluation
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 pr-2">
          {step !== 'configure' && activeTab === 'playground' && (
            <Button
              variant="ghost"
              onClick={resetPlayground}
              leftIcon={<RotateCcw className="w-4 h-4" />}
            >
              New Comparison
            </Button>
          )}
          <WalkthroughToggleButton />
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => {
              setActiveTab('playground')
              setViewingPastId(null)
            }}
            className={`flex items-center gap-2 py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'playground'
                ? 'border-primary-600 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <Mic className="w-4 h-4" />
            Playground
          </button>
          <button
            onClick={() => {
              setActiveTab('voices')
              setViewingPastId(null)
            }}
            className={`flex items-center gap-2 py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'voices'
                ? 'border-primary-600 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <Headphones className="w-4 h-4" />
            Voices
            {customVoices.length > 0 && (
              <span className="ml-1 px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600">
                {customVoices.length}
              </span>
            )}
          </button>
          <button
            onClick={() => {
              setActiveTab('past-simulations')
              setViewingPastId(null)
            }}
            className={`flex items-center gap-2 py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'past-simulations'
                ? 'border-primary-600 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <History className="w-4 h-4" />
            Past Simulations
            {pastComparisons.length > 0 && (
              <span className="ml-1 px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600">
                {pastComparisons.length}
              </span>
            )}
          </button>
        </nav>
      </div>

      {/* Tab Content */}
      {activeTab === 'playground' && <PlaygroundTab />}
      {activeTab === 'voices' && <VoicesTab />}
      {activeTab === 'past-simulations' && <SimulationsTab />}

      {/* Delete Confirmation Modal */}
      {deleteConfirm && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
          onClick={() => setDeleteConfirm(null)}
        >
          <div
            className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">Confirm Delete</h3>
              <button
                onClick={() => setDeleteConfirm(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <p className="text-gray-600 mb-6">{deleteConfirm.message}</p>
            <div className="flex gap-3 justify-end">
              <Button variant="outline" onClick={() => setDeleteConfirm(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  deleteConfirm.onConfirm()
                  setDeleteConfirm(null)
                }}
              >
                Delete
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function VoicePlayground() {
  return (
    <VoicePlaygroundProvider>
      <VoicePlaygroundContent />
    </VoicePlaygroundProvider>
  )
}
