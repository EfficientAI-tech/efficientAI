import { format } from 'date-fns'
import { Loader2, Trash2, ArrowLeft, BarChart3 } from 'lucide-react'
import Button from '../../../../components/Button'
import ProviderLogo, { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { useVoicePlayground } from '../context'
import StatusBadge from './StatusBadge'
import ComparisonResultsView from './ComparisonResultsView'
import AnalyticsPanel from './AnalyticsPanel'

export default function SimulationsTab() {
  const {
    pastSubView,
    setPastSubView,
    viewingPastId,
    setViewingPastId,
    pastComparisons,
    viewedComparison,
    viewedLoading,
    playingId,
    play,
    stop,
    selectedSimIds,
    toggleSimSelection,
    toggleAllSims,
    allSimsSelected,
    someSimsSelected,
    bulkDelete,
    isBulkDeleting,
    deleteComparison,
    isDeleting,
    setDeleteConfirm,
    viewedReportJob,
    isDownloading,
    isCreatingReport,
    downloadReport,
    createReportJob,
    openAsyncReport,
  } = useVoicePlayground()

  // Viewing a specific comparison
  if (viewingPastId) {
    return (
      <div className="space-y-6">
        <button
          onClick={() => {
            setViewingPastId(null)
            stop()
          }}
          className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Past Simulations
        </button>

        {viewedLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-500">
            <Loader2 className="w-6 h-6 animate-spin mr-2" />
            Loading comparison...
          </div>
        ) : viewedComparison ? (
          <>
            <ComparisonResultsView
              comparison={viewedComparison}
              playingId={playingId}
              onPlay={play}
              isDownloading={isDownloading}
              isCreatingReport={isCreatingReport}
              reportJob={viewedReportJob || null}
              onDownloadPdf={(options) => downloadReport(viewedComparison.id, options)}
              onGenerateAsync={(options) => createReportJob(viewedComparison.id, options)}
              onOpenAsyncReport={() => openAsyncReport(viewedReportJob)}
            />

            <div className="flex justify-center">
              <button
                onClick={() => {
                  setViewingPastId(null)
                  stop()
                }}
                className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
                Back to All Simulations
              </button>
            </div>
          </>
        ) : (
          <p className="text-center text-gray-500 py-8">Comparison not found</p>
        )}
      </div>
    )
  }

  // Main simulations list view
  return (
    <div className="space-y-6">
      {/* Sub-navigation: Simulations vs Analytics */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => setPastSubView('simulations')}
          className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
            pastSubView === 'simulations'
              ? 'bg-primary-100 text-primary-700'
              : 'text-gray-600 hover:bg-gray-100'
          }`}
        >
          Simulations
        </button>
        <button
          onClick={() => setPastSubView('analytics')}
          className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors flex items-center gap-2 ${
            pastSubView === 'analytics'
              ? 'bg-primary-100 text-primary-700'
              : 'text-gray-600 hover:bg-gray-100'
          }`}
        >
          <BarChart3 className="w-4 h-4" />
          Analytics & Benchmark
        </button>
      </div>

      {pastSubView === 'simulations' && (
        <div className="bg-white rounded-xl shadow-lg border border-gray-100 overflow-hidden">
          {/* Header with bulk actions */}
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <input
                type="checkbox"
                checked={allSimsSelected}
                onChange={toggleAllSims}
                className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
              />
              <h3 className="font-semibold text-gray-900">Past Simulations</h3>
              <span className="text-sm text-gray-500">({pastComparisons.length} total)</span>
            </div>
            {someSimsSelected && (
              <Button
                variant="ghost"
                size="sm"
                className="text-red-600 hover:text-red-700 hover:bg-red-50"
                onClick={() => {
                  setDeleteConfirm({
                    message: `Delete ${selectedSimIds.size} selected simulation(s)?`,
                    onConfirm: bulkDelete,
                  })
                }}
                disabled={isBulkDeleting}
                leftIcon={
                  isBulkDeleting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Trash2 className="w-4 h-4" />
                  )
                }
              >
                Delete Selected ({selectedSimIds.size})
              </Button>
            )}
          </div>

          {/* List */}
          {pastComparisons.length === 0 ? (
            <div className="px-6 py-12 text-center text-gray-500">
              <p>No past simulations yet. Run a comparison in the Playground tab.</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {pastComparisons.map((sim) => (
                <div
                  key={sim.id}
                  className="px-6 py-4 flex items-center gap-4 hover:bg-gray-50 transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={selectedSimIds.has(sim.id)}
                    onChange={() => toggleSimSelection(sim.id)}
                    className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                  />
                  <div
                    className="flex-1 min-w-0 cursor-pointer"
                    onClick={() => setViewingPastId(sim.id)}
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-medium text-gray-900 truncate">{sim.name}</span>
                      {sim.simulation_id && (
                        <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded font-mono">
                          #{sim.simulation_id}
                        </span>
                      )}
                      <StatusBadge status={sim.status} />
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
                      <span className="flex items-center gap-1.5">
                        <ProviderLogo provider={sim.provider_a} size="sm" />
                        {getProviderInfo(sim.provider_a).label}
                      </span>
                      {sim.provider_b && (
                        <>
                          <span className="text-gray-300">vs</span>
                          <span className="flex items-center gap-1.5">
                            <ProviderLogo provider={sim.provider_b} size="sm" />
                            {getProviderInfo(sim.provider_b).label}
                          </span>
                        </>
                      )}
                      <span className="text-gray-300">•</span>
                      <span>
                        {sim.sample_count} samples{sim.num_runs > 1 && ` × ${sim.num_runs} runs`}
                      </span>
                      <span className="text-gray-300">•</span>
                      <span>{format(new Date(sim.created_at), 'MMM d, yyyy HH:mm')}</span>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-red-500 hover:text-red-700 hover:bg-red-50"
                    onClick={(e) => {
                      e.stopPropagation()
                      setDeleteConfirm({
                        message: `Delete simulation "${sim.name}"?`,
                        onConfirm: () => deleteComparison(sim.id),
                      })
                    }}
                    disabled={isDeleting}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {pastSubView === 'analytics' && <AnalyticsPanel />}
    </div>
  )
}
