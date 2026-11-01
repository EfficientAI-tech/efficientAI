import type { Dispatch, SetStateAction } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertCircle,
  ArrowLeft,
  BarChart3,
  Check,
  Edit3,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-react'
import Button from '../../../../components/Button'
import StatusBadge from '../../../../components/shared/StatusBadge'
import { CallImportAuditMeta } from '../../../../components/callImports/AuditMetaChips'
import CallImportProgressBar from '../CallImportProgressBar'
import { platformImportLabel, platformSkipLines } from '../../platformImportLabel'
import type {
  CallImportDetail,
  CallImportRow,
  CallImportTag,
} from '../../../../types/api'
import type { UseMutationResult } from '@tanstack/react-query'

export type ImportDetailHeaderProps = {
  data: CallImportDetail
  isDeleting: boolean
  canRunEvaluation: boolean
  showWorkflowTabs: boolean
  openRunEvaluationModal: () => void
  rows: CallImportRow[]
  canAppendManualAudio: boolean
  onAppendAudio: () => void
  refetch: () => void
  isFetching: boolean
  isLoading: boolean
  failedImportRowsCount: number
  onRetryFailedImport: () => void
  onDeleteImport: () => void
  isPlatformImport: boolean
  liveProgress: CallImportDetail['platform_progress']
  recordingTotal: number
  recordingCompleted: number
  recordingFailed: number
  diarisationInFlightCount: number
  diarisedCompletedRows: number
  diarisedFailedRows: number
  showCredentialImportWarning: boolean
  pendingCredentialErrorCount: number
  editingMeta: boolean
  setEditingMeta: (editing: boolean) => void
  draftImportName: string
  setDraftImportName: (v: string) => void
  draftDataset: string
  setDraftDataset: (v: string) => void
  draftTagIds: string[]
  setDraftTagIds: Dispatch<SetStateAction<string[]>>
  existingDatasets: string[]
  allTags: CallImportTag[]
  updateMetaMutation: UseMutationResult<
    unknown,
    unknown,
    {
      original_filename?: string | null
      dataset?: string | null
      tag_ids?: string[]
    },
    unknown
  >
  activeTab: 'rows' | 'evaluations' | 'insights'
  setActiveTab: (tab: 'rows' | 'evaluations' | 'insights') => void
  totalRows: number
  evaluationsCount: number
}

export function ImportDetailHeader({
  data,
  isDeleting,
  canRunEvaluation,
  showWorkflowTabs,
  openRunEvaluationModal,
  rows,
  canAppendManualAudio,
  onAppendAudio,
  refetch,
  isFetching,
  isLoading,
  failedImportRowsCount,
  onRetryFailedImport,
  onDeleteImport,
  isPlatformImport,
  liveProgress,
  recordingTotal,
  recordingCompleted,
  recordingFailed,
  diarisationInFlightCount,
  diarisedCompletedRows,
  diarisedFailedRows,
  showCredentialImportWarning,
  pendingCredentialErrorCount,
  editingMeta,
  setEditingMeta,
  draftImportName,
  setDraftImportName,
  draftDataset,
  setDraftDataset,
  draftTagIds,
  setDraftTagIds,
  existingDatasets,
  allTags,
  updateMetaMutation,
  activeTab,
  setActiveTab,
  totalRows,
  evaluationsCount,
}: ImportDetailHeaderProps) {
  return (
    <>
      {isDeleting && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-700">
          This import is being deleted in the background. Actions are disabled
          until removal completes.
        </div>
      )}
      <div className="flex items-center justify-between">
        <Link
          to="/call-imports"
          className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Imports
        </Link>
        <div className="flex items-center gap-2">
          {canRunEvaluation && !isDeleting && showWorkflowTabs && (
            <Button
              variant="primary"
              size="sm"
              onClick={openRunEvaluationModal}
              disabled={!rows.length}
              title={
                !rows.length
                  ? 'No rows to evaluate yet'
                  : 'Open the run dialog — pick metrics, credentials, and models before starting'
              }
            >
              Run Evaluation
            </Button>
          )}
          {canAppendManualAudio && (
            <Button
              variant="outline"
              size="sm"
              leftIcon={<Upload className="h-4 w-4" />}
              onClick={onAppendAudio}
              title="Upload more recordings into this import batch"
            >
              Add recordings
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => refetch()}
            isLoading={isFetching && !isLoading}
            leftIcon={!(isFetching && !isLoading) ? <RefreshCw className="h-4 w-4" /> : undefined}
          >
            Refresh
          </Button>
          {failedImportRowsCount > 0 && (
            <Button
              variant="outline"
              size="sm"
              leftIcon={<RefreshCw className="h-4 w-4" />}
              onClick={onRetryFailedImport}
              className="text-amber-700 hover:text-amber-800 hover:bg-amber-50 border-amber-200"
              title={`Retry ${failedImportRowsCount} failed import row${
                failedImportRowsCount === 1 ? '' : 's'
              }`}
            >
              Retry failed imports ({failedImportRowsCount})
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={onDeleteImport}
            disabled={isDeleting}
            leftIcon={<Trash2 className="h-4 w-4" />}
            className="text-red-600 hover:text-red-700 hover:bg-red-50"
          >
            Delete Import
          </Button>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg p-6">
        <div className="space-y-4">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold text-gray-900 truncate">
              {(data.source_format || '').toLowerCase() === 'platform'
                ? platformImportLabel(data)
                : data.original_filename || '(unnamed import)'}
            </h1>
            <div className="mt-1 text-xs text-gray-500 font-mono">{data.id}</div>
            <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 min-w-0 max-w-full text-sm text-gray-600">
              <span className="inline-flex items-center gap-1.5 shrink-0">
                {data.latest_evaluation_status ? (
                  <>
                    <span className="text-xs text-gray-500">Latest evaluation</span>
                    <StatusBadge status={data.latest_evaluation_status} />
                  </>
                ) : (
                  <StatusBadge status={data.status} />
                )}
              </span>
              <span className="capitalize shrink-0">
                Provider:{' '}
                <span className="font-medium text-gray-800">
                  {data.provider || (
                    <span className="text-gray-400 italic normal-case font-normal">
                      not selected yet
                    </span>
                  )}
                </span>
              </span>
              {isPlatformImport && (
                <span className="shrink-0">
                  Agent:{' '}
                  <span className="font-medium text-gray-800">
                    {(data.platform_agents || []).length === 0
                      ? 'All agents'
                      : (data.platform_agents || [])
                          .map((agent) =>
                            agent.medium
                              ? `${agent.name} · ${agent.medium}`
                              : agent.name,
                          )
                          .join(', ')}
                  </span>
                </span>
              )}
              <CallImportAuditMeta
                inline
                createdAt={data.created_at}
                updatedAt={data.updated_at}
                createdByEmail={data.created_by_email}
                lastUpdatedByEmail={data.last_updated_by_email}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded-lg border border-slate-200 bg-slate-50/80 p-3 shadow-sm min-w-0">
              <h3 className="text-sm font-semibold text-slate-900 mb-2.5 pb-2 border-b border-slate-200">
                Recording import
              </h3>
              <CallImportProgressBar
                total={recordingTotal}
                completed={recordingCompleted}
                failed={recordingFailed}
                deleting={isDeleting}
              />
              {isPlatformImport &&
                (liveProgress?.discovery_status || data.discovery_status) && (
                  <p className="mt-2 text-xs text-gray-600">
                    Discovery {liveProgress?.discovery_status || data.discovery_status}
                    {liveProgress
                      ? ` · ${liveProgress.discovery.slices_completed}/${liveProgress.discovery.slices_total} days`
                      : ''}
                    {data.paused_at || liveProgress?.paused ? ' · paused' : ''}
                  </p>
                )}
              {platformSkipLines(liveProgress?.skip_counts ?? data.skip_counts).length > 0 && (
                <p className="mt-2 text-xs text-gray-600">
                  {platformSkipLines(liveProgress?.skip_counts ?? data.skip_counts).join(' · ')}
                </p>
              )}
              <div className="mt-2.5 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="bg-white rounded-md border border-slate-100 p-2">
                  <div className="text-gray-500">Total</div>
                  <div className="font-semibold text-gray-900">{recordingTotal}</div>
                </div>
                <div className="bg-white rounded-md border border-green-100 p-2">
                  <div className="text-green-700">Completed</div>
                  <div className="font-semibold text-green-800">{recordingCompleted}</div>
                </div>
                <div className="bg-white rounded-md border border-red-100 p-2">
                  <div className="text-red-700">Failed</div>
                  <div className="font-semibold text-red-800">{recordingFailed}</div>
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-violet-200 bg-violet-50/50 p-3 shadow-sm min-w-0">
              <div className="flex items-center justify-between gap-2 mb-2.5 pb-2 border-b border-violet-200">
                <h3 className="text-sm font-semibold text-violet-950">
                  Transcription &amp; diarisation
                </h3>
                {diarisationInFlightCount > 0 && (
                  <span className="inline-flex items-center gap-1 text-[11px] font-medium text-violet-700 whitespace-nowrap">
                    <RefreshCw className="h-3 w-3 animate-spin" />
                    {diarisationInFlightCount} in progress
                  </span>
                )}
              </div>
              <CallImportProgressBar
                total={data.total_rows}
                completed={diarisedCompletedRows}
                failed={diarisedFailedRows}
                deleting={isDeleting}
              />
              <div className="mt-2.5 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="bg-white rounded-md border border-violet-100 p-2">
                  <div className="text-gray-500">Total</div>
                  <div className="font-semibold text-gray-900">{data.total_rows}</div>
                </div>
                <div className="bg-white rounded-md border border-green-100 p-2">
                  <div className="text-green-700">Completed</div>
                  <div className="font-semibold text-green-800">
                    {diarisedCompletedRows}
                  </div>
                </div>
                <div className="bg-white rounded-md border border-red-100 p-2">
                  <div className="text-red-700">Failed</div>
                  <div className="font-semibold text-red-800">
                    {diarisedFailedRows}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-4 border-t border-gray-100 pt-4">
          {!editingMeta ? (
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Dataset:
                  </span>
                  {data.dataset ? (
                    <span className="inline-flex items-center text-sm font-medium text-gray-800 bg-gray-100 rounded px-2 py-0.5">
                      {data.dataset}
                    </span>
                  ) : (
                    <span className="text-sm text-gray-400 italic">none</span>
                  )}
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Tags:
                  </span>
                  {data.tags.length > 0 ? (
                    data.tags.map((tag) => (
                      <span
                        key={tag.id}
                        className="inline-flex items-center text-xs uppercase tracking-wide rounded-full px-2 py-0.5 border"
                        style={{
                          borderColor: tag.color || '#d1d5db',
                          color: tag.color || '#4b5563',
                        }}
                      >
                        {tag.name}
                      </span>
                    ))
                  ) : (
                    <span className="text-sm text-gray-400 italic">none</span>
                  )}
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<Edit3 className="h-4 w-4" />}
                onClick={() => {
                  setDraftImportName(data.original_filename || '')
                  setDraftDataset(data.dataset || '')
                  setDraftTagIds(data.tags.map((t) => t.id))
                  setEditingMeta(true)
                }}
              >
                Edit name / dataset / tags
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <label
                  htmlFor="import-name-edit"
                  className="block text-xs font-medium text-gray-600 uppercase tracking-wide mb-1"
                >
                  Import name
                </label>
                <input
                  id="import-name-edit"
                  type="text"
                  value={draftImportName}
                  onChange={(e) => setDraftImportName(e.target.value)}
                  placeholder="Leave blank to clear"
                  className="w-full max-w-sm px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />
              </div>
              <div>
                <label
                  htmlFor="dataset-edit"
                  className="block text-xs font-medium text-gray-600 uppercase tracking-wide mb-1"
                >
                  Dataset
                </label>
                <input
                  id="dataset-edit"
                  type="text"
                  list="dataset-edit-suggestions"
                  value={draftDataset}
                  onChange={(e) => setDraftDataset(e.target.value)}
                  placeholder="Leave blank to clear"
                  className="w-full max-w-sm px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />
                <datalist id="dataset-edit-suggestions">
                  {existingDatasets.map((d) => (
                    <option key={d} value={d} />
                  ))}
                </datalist>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 uppercase tracking-wide mb-1">
                  Tags
                </label>
                {allTags.length === 0 ? (
                  <p className="text-xs text-gray-500">
                    No tags created yet.{' '}
                    <Link
                      to="/call-imports/tags"
                      className="text-primary-600 hover:text-primary-700 underline"
                    >
                      Create tags
                    </Link>
                    .
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {allTags.map((tag: CallImportTag) => {
                      const active = draftTagIds.includes(tag.id)
                      return (
                        <button
                          key={tag.id}
                          type="button"
                          onClick={() =>
                            setDraftTagIds((prev) =>
                              prev.includes(tag.id)
                                ? prev.filter((t) => t !== tag.id)
                                : [...prev, tag.id],
                            )
                          }
                          className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                            active
                              ? 'bg-primary-600 border-primary-600 text-white'
                              : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
                          }`}
                          style={
                            !active && tag.color
                              ? { borderColor: tag.color, color: tag.color }
                              : undefined
                          }
                        >
                          {tag.name}
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  leftIcon={<Check className="h-4 w-4" />}
                  isLoading={updateMetaMutation.isPending}
                  onClick={() =>
                    updateMetaMutation.mutate({
                      original_filename: draftImportName.trim()
                        ? draftImportName.trim()
                        : null,
                      dataset: draftDataset.trim() ? draftDataset.trim() : null,
                      tag_ids: draftTagIds,
                    })
                  }
                >
                  Save
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setEditingMeta(false)}
                  disabled={updateMetaMutation.isPending}
                >
                  Cancel
                </Button>
              </div>
              {updateMetaMutation.isError && (
                <p className="text-xs text-red-600">
                  {(updateMetaMutation.error as any)?.response?.data?.detail ||
                    'Failed to update.'}
                </p>
              )}
            </div>
          )}
        </div>

        {data.error_message && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-4 w-4 text-red-600 mt-0.5" />
              <p className="text-sm text-red-800">{data.error_message}</p>
            </div>
          </div>
        )}

        {showCredentialImportWarning && (
          <div className="mt-4 bg-amber-50 border border-amber-200 rounded-lg p-3">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-4 w-4 text-amber-600 mt-0.5 flex-shrink-0" />
              <div className="text-sm text-amber-900 space-y-1">
                <p>
                  {pendingCredentialErrorCount} row
                  {pendingCredentialErrorCount === 1 ? '' : 's'} failed to fetch
                  recordings due to telephony credential errors. Update credentials in
                  Integrations, then use Retry failed to try again.
                </p>
              </div>
            </div>
          </div>
        )}

        {(data.source_row_skips?.length ?? 0) > 0 && data.total_rows > 0 && (
          <div className="mt-4 bg-amber-50 border border-amber-200 rounded-lg p-3">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-4 w-4 text-amber-600 mt-0.5 flex-shrink-0" />
              <div className="text-sm text-amber-900 space-y-2 min-w-0">
                <p>
                  Imported {data.total_rows} row
                  {data.total_rows === 1 ? '' : 's'}.{' '}
                  {data.source_row_skips!.length} source row
                  {data.source_row_skips!.length === 1 ? '' : 's'} skipped
                  — missing or invalid conversation ID / recording URL.
                </p>
                <ul className="list-disc pl-5 space-y-0.5 max-h-40 overflow-y-auto text-xs">
                  {data.source_row_skips!.slice(0, 50).map((skip) => (
                    <li key={`${skip.source_row}-${skip.reason}`}>
                      {skip.message}
                    </li>
                  ))}
                </ul>
                {data.source_row_skips!.length > 50 && (
                  <p className="text-xs text-amber-800">
                    and {data.source_row_skips!.length - 50} more skipped row
                    {data.source_row_skips!.length - 50 === 1 ? '' : 's'}.
                  </p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {showWorkflowTabs ? (
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6" aria-label="Call import sections">
          <button
            type="button"
            onClick={() => setActiveTab('rows')}
            className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium transition ${
              activeTab === 'rows'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
            aria-current={activeTab === 'rows' ? 'page' : undefined}
          >
            Rows
            <span className="ml-2 inline-flex items-center justify-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
              {totalRows}
            </span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('evaluations')}
            className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium transition ${
              activeTab === 'evaluations'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
            aria-current={activeTab === 'evaluations' ? 'page' : undefined}
          >
            Evaluations
            <span className="ml-2 inline-flex items-center justify-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
              {evaluationsCount}
            </span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('insights')}
            className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium transition ${
              activeTab === 'insights'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
            aria-current={activeTab === 'insights' ? 'page' : undefined}
          >
            <BarChart3 className="h-3.5 w-3.5 inline mr-1 -mt-0.5" />
            Insights
          </button>
        </nav>
      </div>
      ) : null}
    </>
  )
}
