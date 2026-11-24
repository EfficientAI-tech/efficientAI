import { Plus, Trash2 } from 'lucide-react'
import Button from '../../../../components/Button'
import MetricPickerPanel from '../MetricPickerPanel'

type StudioWizardMetricsStepProps = {
  metricTab: 'active' | 'drafts'
  onMetricTabChange: (tab: 'active' | 'drafts') => void
  metricsForPicker: any[]
  selectedMetricIds: string[]
  onSelectedMetricIdsChange: (ids: string[]) => void
  canPromoteSelectedDraft: boolean
  onPromoteSelectedDraft: () => void
  promotePending: boolean
  canDeleteSelectedDrafts: boolean
  onDeleteSelectedDrafts: () => void
  deletePending: boolean
  onCreateDraft: () => void
}

export default function StudioWizardMetricsStep({
  metricTab,
  onMetricTabChange,
  metricsForPicker,
  selectedMetricIds,
  onSelectedMetricIdsChange,
  canPromoteSelectedDraft,
  onPromoteSelectedDraft,
  promotePending,
  canDeleteSelectedDrafts,
  onDeleteSelectedDrafts,
  deletePending,
  onCreateDraft,
}: StudioWizardMetricsStepProps) {
  return (
    <div className="flex flex-col h-full min-h-0 gap-4">
      <div className="flex items-center justify-between gap-2 shrink-0 flex-wrap">
        <div className="inline-flex rounded-md border border-gray-200 bg-gray-50 p-0.5 text-xs font-medium">
          {(['active', 'drafts'] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => onMetricTabChange(tab)}
              className={`px-3 py-1.5 rounded ${
                metricTab === tab
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {tab === 'active' ? 'Active' : 'Drafts'}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {metricTab === 'drafts' && (
            <>
              <Button
                variant="ghost"
                size="sm"
                disabled={!canPromoteSelectedDraft || promotePending || deletePending}
                onClick={onPromoteSelectedDraft}
              >
                Promote
              </Button>
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<Trash2 className="h-4 w-4" />}
                disabled={!canDeleteSelectedDrafts || promotePending || deletePending}
                onClick={onDeleteSelectedDrafts}
                className="text-red-700 hover:text-red-900"
              >
                Delete
              </Button>
            </>
          )}
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<Plus className="h-4 w-4" />}
            onClick={onCreateDraft}
          >
            Draft
          </Button>
        </div>
      </div>
      {metricTab === 'drafts' && (
        <p className="text-xs text-gray-500 shrink-0">
          Select draft metrics in the list, then use Promote or Delete above.
        </p>
      )}
      <MetricPickerPanel
        metrics={metricsForPicker}
        selectedMetricIds={selectedMetricIds}
        onChange={onSelectedMetricIdsChange}
        listClassName="flex-1 min-h-0 overflow-y-auto border border-gray-200 rounded-lg p-2"
        emptyMessage={
          metricTab === 'drafts'
            ? 'No draft metrics yet. Create one to experiment.'
            : 'No enabled metrics in this workspace. Enable metrics on the Manage tab first.'
        }
      />
    </div>
  )
}