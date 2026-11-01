import {
  AlertCircle,
  Check,
  Copy,
  Download,
  FileText,
  ListTree,
  Mic,
  Play,
  RefreshCw,
  Search,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import type { UseMutationResult } from '@tanstack/react-query'
import { formatDiarisationError } from '../../../lib/diarisationErrors'
import type { CallImportRow } from '../../../types/api'
import Button from '../../../components/Button'
import Pagination from '../../../components/Pagination'
import StatusBadge from '../../../components/shared/StatusBadge'
import DiariseStatusPill from '../../../components/callImports/DiariseStatusPill'
import { CallRowDetailSplitLayout } from './CallRowDetailSplitLayout'
import { CallRowSidePanel } from './CallRowSidePanel'
import {
  CallImportRowSidePanelContent,
  type CallImportRowSidePanelTabId,
} from './CallImportRowSidePanelContent'
import { platformSkipLines } from '../platformImportLabel'
import {
  getRawColumnEntries,
  ROW_PAGE_SIZE,
  type DiarisedStatusFilter,
} from '../hooks/useImportDetailRows'

function isNonRetryableError(message: string | null | undefined): boolean {
  if (!message) return false
  return /(401|403|404|forbidden|unauthor|not found|exceeds|too large|invalid content)/i.test(message)
}

export type ImportRowsTabProps = {
  data: {
    source_format?: string | null
    skip_counts?: Record<string, number> | null
  }
  totalRows: number
  rows: CallImportRow[]
  rowOffset: number
  setRowOffset: React.Dispatch<React.SetStateAction<number>>
  filteredTotalRows: number
  hasActiveFilter: boolean
  rowSearchInput: string
  setRowSearchInput: (value: string) => void
  rowSearchQuery: string
  diarisedStatusFilter: DiarisedStatusFilter
  setDiarisedStatusFilter: (value: DiarisedStatusFilter) => void
  selectedCount: number
  selectedRowIds: Set<string>
  setSelectedRowIds: React.Dispatch<React.SetStateAction<Set<string>>>
  setBulkSelectionFilter: React.Dispatch<
    React.SetStateAction<{ q?: string; diarised_status?: string } | null>
  >
  setBulkActionError: (message: string | null) => void
  setBulkActionResult: (message: string | null) => void
  setShowBulkActionsModal: (open: boolean) => void
  allOnPageSelected: boolean
  selectedOnPageCount: number
  listRowFilter: () => { q?: string; diarised_status?: string }
  bulkSelectionFilter: { q?: string; diarised_status?: string } | null
  allMatchingSelected: boolean
  selectAllError: string | null
  setSelectAllError: (message: string | null) => void
  rowPage: number
  rowTotalPages: number
  selectedRowId: string | null
  setSelectedRowId: React.Dispatch<React.SetStateAction<string | null>>
  selectedRow: CallImportRow | null
  copiedRowId: string | null
  handleCopyConversationId: (row: CallImportRow, event: React.MouseEvent) => void
  handleDownload: (row: CallImportRow) => void | Promise<void>
  openTranscribeModal: (rows: CallImportRow[]) => void
  cancelDiarisationMutation: UseMutationResult<unknown, unknown, { rowId: string }, unknown>
  cancellingRowId: string | null
  setDeleteError: (message: string | null) => void
  setPendingDeleteRow: (row: CallImportRow | null) => void
  deleteRowMutation: UseMutationResult<
    unknown,
    unknown,
    { importId: string; rowId: string },
    unknown
  >
  pendingDeleteRow: CallImportRow | null
  selectedRowDetail: CallImportRow | undefined
  rowPanelTab: CallImportRowSidePanelTabId
  setRowPanelTab: (tab: CallImportRowSidePanelTabId) => void
  copiedTranscriptField: { rowId: string; field: 'production' | 'diarised' } | null
  handleCopyTranscript: (
    row: CallImportRow,
    field: 'production' | 'diarised',
    event: React.MouseEvent,
  ) => void
  swapSpeakersMutation: UseMutationResult<unknown, unknown, { rowId: string }, unknown>
  swappingRowId: string | null
  swapError: string | null
  setSwapError: (message: string | null) => void
}

export default function ImportRowsTab(props: ImportRowsTabProps) {
  const {
    data,
    totalRows,
    rows,
    rowOffset,
    setRowOffset,
    filteredTotalRows,
    hasActiveFilter,
    rowSearchInput,
    setRowSearchInput,
    rowSearchQuery,
    diarisedStatusFilter,
    setDiarisedStatusFilter,
    selectedCount,
    selectedRowIds,
    setSelectedRowIds,
    setBulkSelectionFilter,
    setBulkActionError,
    setBulkActionResult,
    setShowBulkActionsModal,
    allOnPageSelected,
    selectedOnPageCount,
    listRowFilter,
    allMatchingSelected,
    selectAllError,
    setSelectAllError,
    rowPage,
    rowTotalPages,
    selectedRowId,
    setSelectedRowId,
    selectedRow,
    copiedRowId,
    handleCopyConversationId,
    handleDownload,
    openTranscribeModal,
    cancelDiarisationMutation,
    cancellingRowId,
    setDeleteError,
    setPendingDeleteRow,
    deleteRowMutation,
    pendingDeleteRow,
    selectedRowDetail,
    rowPanelTab,
    setRowPanelTab,
    copiedTranscriptField,
    handleCopyTranscript,
    swapSpeakersMutation,
    swappingRowId,
    swapError,
    setSwapError,
  } = props

  return (
<div className="bg-white shadow rounded-lg p-6">
  <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
    <h2 className="text-lg font-semibold text-gray-900">Rows</h2>
    <div className="flex items-center gap-3 flex-wrap">
      <p className="text-sm text-gray-500">
        Showing {rows.length === 0 ? 0 : rowOffset + 1}&ndash;
        {rowOffset + rows.length} of {filteredTotalRows}
        {hasActiveFilter ? ` (filtered from ${totalRows})` : ''}
      </p>
    </div>
  </div>

  <div className="mb-4 flex items-stretch gap-2 flex-wrap">
    <div className="relative flex-1 min-w-[260px] max-w-md">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
      <input
        type="text"
        value={rowSearchInput}
        onChange={(e) => setRowSearchInput(e.target.value)}
        placeholder="Search by Conversation ID…"
        aria-label="Search rows by Conversation ID"
        className="w-full pl-9 pr-9 py-2 text-sm border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500"
      />
      {rowSearchInput && (
        <button
          type="button"
          onClick={() => setRowSearchInput('')}
          className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100"
          aria-label="Clear search"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
    {/* Diarisation status filter chips — finally lets the user
        find rows where diarisation failed without expanding every
        row in turn. The active chip drives ``diarised_status`` on
        the rows query and updates ``filtered_total_rows``. */}
    <div
      className="flex items-center gap-1 flex-wrap"
      role="group"
      aria-label="Filter rows by diarisation status"
    >
      <span className="text-[11px] uppercase tracking-wide text-gray-500 mr-1">
        Diarisation:
      </span>
      {(
        [
          { id: 'all', label: 'All' },
          { id: 'pending', label: 'Pending' },
          { id: 'running', label: 'Running' },
          { id: 'completed', label: 'Completed' },
          { id: 'failed', label: 'Failed' },
        ] as Array<{ id: DiarisedStatusFilter; label: string }>
      ).map((chip) => {
        const active = diarisedStatusFilter === chip.id
        return (
          <button
            key={chip.id}
            type="button"
            onClick={() => setDiarisedStatusFilter(chip.id)}
            className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
              active
                ? chip.id === 'failed'
                  ? 'bg-red-600 border-red-600 text-white'
                  : 'bg-primary-600 border-primary-600 text-white'
                : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
            }`}
            aria-pressed={active}
          >
            {chip.label}
          </button>
        )
      })}
    </div>
    {selectedCount > 0 && (
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-gray-600">
          {selectedCount} selected
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setSelectedRowIds(new Set())
            setBulkSelectionFilter(null)
          }}
        >
          Clear
        </Button>
        {/* Single entry point for every multi-row operation:
            Diarise, Stop diarisation, Delete. The modal
            surfaces per-action counts and explicit confirm
            affordances, so the toolbar can stay uncluttered
            even as we keep adding bulk verbs. */}
        <Button
          variant="ghost"
          size="sm"
          leftIcon={<ListTree className="h-4 w-4" />}
          onClick={() => {
            setBulkActionError(null)
            setBulkActionResult(null)
            setShowBulkActionsModal(true)
          }}
          className="text-primary-700 hover:text-primary-800 hover:bg-primary-50"
        >
          Bulk actions
        </Button>
      </div>
    )}
  </div>

  {rows.length === 0 ? (
    <div className="text-center py-12 text-gray-500">
      <FileText className="h-12 w-12 mx-auto mb-3 text-gray-300" />
      {rowSearchQuery ? (
        <p>
          No rows match{' '}
          <span className="font-mono text-gray-700">
            &quot;{rowSearchQuery}&quot;
          </span>
          {diarisedStatusFilter !== 'all'
            ? ` with diarisation status ${diarisedStatusFilter}.`
            : '.'}
        </p>
      ) : diarisedStatusFilter !== 'all' ? (
        <p>
          No rows with diarisation status{' '}
          <span className="font-medium text-gray-700">
            {diarisedStatusFilter}
          </span>
          .
        </p>
      ) : (data.source_format || '').toLowerCase() === 'platform' &&
        platformSkipLines(data.skip_counts).length > 0 ? (
        <div className="space-y-1">
          <p>No new calls in this window.</p>
          <p className="text-sm text-gray-700">
            {platformSkipLines(data.skip_counts).join(' · ')}
          </p>
        </div>
      ) : (
        <p>No rows in this slice.</p>
      )}
    </div>
  ) : (
    <CallRowDetailSplitLayout
      panelOpen={!!selectedRow}
      list={
      <div className="space-y-2">
      <div className="flex items-center gap-3 px-3 py-2 border border-gray-200 rounded-lg bg-gray-50 flex-wrap">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            aria-label="Select all rows on this page"
            checked={allOnPageSelected}
            ref={(el) => {
              if (el)
                el.indeterminate =
                  selectedOnPageCount > 0 && !allOnPageSelected
            }}
            onChange={(e) => {
              if (e.target.checked) {
                // Add every on-page row to the selection without
                // disturbing rows the user already ticked on
                // other pages.
                setSelectedRowIds((prev) => {
                  const next = new Set(prev)
                  for (const r of rows) next.add(r.id)
                  return next
                })
              } else {
                // Drop only the on-page rows from the selection
                // so the user can unselect this page without
                // wiping cross-page picks.
                setSelectedRowIds((prev) => {
                  const next = new Set(prev)
                  for (const r of rows) next.delete(r.id)
                  return next
                })
              }
            }}
          />
          <span className="text-xs text-gray-600">
            {allOnPageSelected
              ? `All ${rows.length} on this page selected`
              : selectedOnPageCount > 0
              ? `${selectedOnPageCount} of ${rows.length} on this page selected`
              : `Select all on this page (${rows.length})`}
          </span>
        </div>
        {/* "Select all in import" affordance — only shown once
            the on-page checkbox is satisfied AND there are off-page
            rows that the user could still benefit from selecting.
            Clicking it hits the lightweight ``/row-ids`` endpoint
            with the active filters so the selection respects the
            search / status chips. */}
        {allOnPageSelected &&
          filteredTotalRows > rows.length &&
          !allMatchingSelected && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400">·</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSelectAllError(null)
                  setBulkSelectionFilter(listRowFilter())
                }}
              >
                {`Select all ${filteredTotalRows} rows in this import${
                  hasActiveFilter ? ' (matching filters)' : ''
                }`}
              </Button>
            </div>
          )}
        {allMatchingSelected &&
          filteredTotalRows > rows.length && (
            <span className="text-xs text-primary-700">
              All {filteredTotalRows} matching rows selected.
            </span>
          )}
      </div>
      {selectAllError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
          {selectAllError}
        </div>
      )}
      {/* Top pagination — mirrors the bottom bar so users don't
          have to scroll past hundreds of rows to flip pages.
          Renders nothing when there's only one page of results. */}
      <Pagination
        page={rowPage}
        pageCount={rowTotalPages}
        total={filteredTotalRows}
        pageSize={ROW_PAGE_SIZE}
        variant="card"
        className="mb-2"
        onPrev={() =>
          setRowOffset((o) => Math.max(0, o - ROW_PAGE_SIZE))
        }
        onNext={() =>
          setRowOffset((o) =>
            o + ROW_PAGE_SIZE >= filteredTotalRows
              ? o
              : o + ROW_PAGE_SIZE,
          )
        }
      />
      {rows.map((row) => {
        const hasRecording = !!row.recording_s3_key
        const isPanelOpen = selectedRowId === row.id
        const isSelected = selectedRowIds.has(row.id)
        return (
          <div
            key={row.id}
            role="button"
            tabIndex={0}
            onClick={() =>
              setSelectedRowId((prev) => (prev === row.id ? null : row.id))
            }
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                setSelectedRowId((prev) => (prev === row.id ? null : row.id))
              }
            }}
            className={`border rounded-lg bg-white overflow-hidden transition-shadow hover:shadow-sm cursor-pointer ${
              isPanelOpen
                ? 'border-primary-500 ring-1 ring-primary-200'
                : isSelected
                  ? 'border-primary-400 bg-primary-50/30'
                  : 'border-gray-200'
            }`}
          >
            <div className="flex items-center gap-2 px-3 py-2.5">
              <input
                type="checkbox"
                aria-label={`Select row ${row.conversation_id}`}
                checked={isSelected}
                onChange={(e) => {
                  setSelectedRowIds((prev) => {
                    const next = new Set(prev)
                    if (e.target.checked) next.add(row.id)
                    else next.delete(row.id)
                    return next
                  })
                }}
                onClick={(e) => e.stopPropagation()}
              />
              <div className="flex items-center gap-3 flex-1 min-w-0 text-left -mx-1 px-1 py-1">
                <span className="text-xs text-gray-400 w-10 tabular-nums flex-shrink-0">
                  #{row.row_index + 1}
                </span>
                {/*
                  Conversation ID stays selectable; a normal click
                  still opens the docked detail panel on the row.
                  Only the copy control stops propagation.
                 */}
                <span
                  className="font-mono text-sm text-gray-900 truncate flex-1 min-w-0 select-text"
                  title={row.conversation_id}
                >
                  {row.conversation_id}
                </span>
                <span
                  role="button"
                  tabIndex={0}
                  aria-label={
                    copiedRowId === row.id
                      ? `Copied ${row.conversation_id}`
                      : `Copy ${row.conversation_id}`
                  }
                  title={
                    copiedRowId === row.id
                      ? 'Copied!'
                      : 'Copy conversation ID'
                  }
                  onClick={(e) => handleCopyConversationId(row, e)}
                  onMouseDown={(e) => e.stopPropagation()}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      handleCopyConversationId(
                        row,
                        e as unknown as React.MouseEvent,
                      )
                    }
                  }}
                  className={`flex-shrink-0 inline-flex items-center justify-center w-6 h-6 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 cursor-pointer ${
                    copiedRowId === row.id
                      ? 'text-green-600 bg-green-50'
                      : 'text-gray-400 hover:text-primary-600 hover:bg-primary-50'
                  }`}
                >
                  {copiedRowId === row.id ? (
                    <Check className="h-3.5 w-3.5" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                </span>
                <StatusBadge status={row.status} size="sm" />
                <DiariseStatusPill status={row.diarised_transcript_status} />
              </div>

              <div
                className="flex items-center gap-1 flex-shrink-0"
                onClick={(e) => e.stopPropagation()}
              >
                {hasRecording ? (
                  <>
                    <button
                      type="button"
                      onClick={() => setSelectedRowId(row.id)}
                      title="Open recording in side panel"
                      className={`p-1.5 rounded transition-colors ${
                        isPanelOpen
                          ? 'text-green-600 bg-green-50 hover:bg-green-100'
                          : 'text-blue-600 hover:bg-blue-50'
                      }`}
                    >
                      <Play className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDownload(row)}
                      title="Download recording"
                      className="p-1.5 rounded text-gray-500 hover:text-primary-600 hover:bg-primary-50 transition-colors"
                    >
                      <Download className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => openTranscribeModal([row])}
                      disabled={
                        row.diarised_transcript_status === 'pending' ||
                        row.diarised_transcript_status === 'running'
                      }
                      title={
                        row.diarised_transcript_status === 'pending' ||
                        row.diarised_transcript_status === 'running'
                          ? 'Diarisation in progress'
                          : 'Diarise this row'
                      }
                      className="p-1.5 rounded text-gray-500 hover:text-purple-600 hover:bg-purple-50 transition-colors disabled:opacity-40"
                    >
                      {row.diarised_transcript_status === 'pending' ||
                      row.diarised_transcript_status === 'running' ? (
                        <RefreshCw className="h-4 w-4 animate-spin" />
                      ) : (
                        <Mic className="h-4 w-4" />
                      )}
                    </button>
                    {/*
                      Stop / abort button. Only visible while
                      the diarisation pipeline is actually in
                      flight (``pending`` queued OR ``running``
                      inside the worker). Calls the cancel
                      endpoint which revokes the Celery task
                      (SIGTERM) and stamps the row with a
                      "Cancelled by user" failure so the UI
                      immediately reflects the abort. Disabled
                      while we already have an in-flight cancel
                      request for THIS row so a double-click
                      doesn't fire two revokes (it's idempotent
                      on the server, but the spinner state would
                      flicker).
                     */}
                    {(row.diarised_transcript_status === 'pending' ||
                      row.diarised_transcript_status === 'running') && (
                      <button
                        type="button"
                        onClick={() =>
                          cancelDiarisationMutation.mutate({
                            rowId: row.id,
                          })
                        }
                        disabled={cancellingRowId === row.id}
                        title="Stop diarisation"
                        aria-label={`Stop diarisation for ${row.conversation_id}`}
                        className="p-1.5 rounded text-gray-500 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40"
                      >
                        {cancellingRowId === row.id ? (
                          <RefreshCw className="h-4 w-4 animate-spin" />
                        ) : (
                          <Square className="h-4 w-4" />
                        )}
                      </button>
                    )}
                  </>
                ) : (
                  <span className="text-[11px] text-gray-400 px-2">
                    {row.status === 'failed' ? 'no audio' : 'pending'}
                  </span>
                )}
                <button
                  type="button"
                  aria-label={`Delete recording for ${row.conversation_id}`}
                  title="Delete row"
                  onClick={() => {
                    setDeleteError(null)
                    setPendingDeleteRow(row)
                  }}
                  disabled={
                    deleteRowMutation.isPending &&
                    pendingDeleteRow?.id === row.id
                  }
                  className="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>

            {row.status === 'failed' && row.error_message && (
              <div className="border-t border-red-100 bg-red-50 px-3 py-2 text-xs text-red-800 flex items-start gap-2">
                <AlertCircle className="h-3.5 w-3.5 text-red-600 flex-shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1 break-words">
                  <span className="font-medium">Error:</span> {row.error_message}
                  {isNonRetryableError(row.error_message) && (
                    <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-100 text-red-700">
                      no retry
                    </span>
                  )}
                </div>
              </div>
            )}

            {row.status === 'pending' && row.error_message && (
              <div className="border-t border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-900 flex items-start gap-2">
                <AlertCircle className="h-3.5 w-3.5 text-amber-600 flex-shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1 break-words">
                  <span className="font-medium">Retry pending:</span> {row.error_message}
                </div>
              </div>
            )}

            {/* Surface diarisation-specific failures even when
                the row's recording download itself succeeded.
                Previously these only showed inside the expanded
                panel, so the new "Failed" filter chip would land
                the user on rows with no inline indication of why
                they failed. */}
            {row.diarised_transcript_status === 'failed' &&
              row.diarised_transcript_error && (
                <div className="border-t border-red-100 bg-red-50 px-3 py-2 text-xs text-red-800 flex items-start gap-2">
                  <AlertCircle className="h-3.5 w-3.5 text-red-600 flex-shrink-0 mt-0.5" />
                  <div className="min-w-0 flex-1 break-words">
                    <span className="font-medium">
                      Diarisation error:
                    </span>{' '}
                    {formatDiarisationError(row.diarised_transcript_error)}
                  </div>
                </div>
              )}
            {row.diarised_transcript_status === 'pending' &&
              row.diarised_transcript_error?.includes('Waiting for') && (
                <div className="border-t border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-900 flex items-start gap-2">
                  <AlertCircle className="h-3.5 w-3.5 text-amber-600 flex-shrink-0 mt-0.5" />
                  <div className="min-w-0 flex-1 break-words">
                    {formatDiarisationError(row.diarised_transcript_error)}
                  </div>
                </div>
              )}

          </div>
        )
      })}

      <Pagination
        page={rowPage}
        pageCount={rowTotalPages}
        total={filteredTotalRows}
        pageSize={ROW_PAGE_SIZE}
        variant="card"
        className="mt-3"
        onPrev={() =>
          setRowOffset((o) => Math.max(0, o - ROW_PAGE_SIZE))
        }
        onNext={() =>
          setRowOffset((o) =>
            o + ROW_PAGE_SIZE >= filteredTotalRows
              ? o
              : o + ROW_PAGE_SIZE,
          )
        }
      />
      </div>
      }
      panel={
        selectedRow ? (
        <CallRowSidePanel
          onClose={() => setSelectedRowId(null)}
          title={selectedRow.conversation_id}
          headerMeta={
            <>
              <StatusBadge status={selectedRow.status} size="sm" />
              <DiariseStatusPill status={selectedRow.diarised_transcript_status} />
              <span className="text-xs text-gray-500">
                Row #{selectedRow.row_index + 1}
              </span>
            </>
          }
          recordingS3Key={selectedRow.recording_s3_key}
          recordingUrl={selectedRow.recording_url}
          tabs={[
            { id: 'production', label: 'Production' },
            { id: 'diarised', label: 'Diarised' },
            { id: 'metadata', label: 'Metadata' },
          ]}
          activeTab={rowPanelTab}
          onTabChange={(tabId) =>
            setRowPanelTab(tabId as CallImportRowSidePanelTabId)
          }
        >
          {selectedRowDetail ? (
            <CallImportRowSidePanelContent
              row={selectedRowDetail}
              activeTab={rowPanelTab}
              rawColumnEntries={getRawColumnEntries(selectedRowDetail)}
              hasRecording={!!selectedRowDetail.recording_s3_key}
              copiedTranscriptField={copiedTranscriptField}
              onCopyTranscript={handleCopyTranscript}
              onDiarise={() => openTranscribeModal([selectedRowDetail])}
              onSwapSpeakers={() =>
                swapSpeakersMutation.mutate({ rowId: selectedRowDetail.id })
              }
              swappingRowId={swappingRowId}
              swapError={swapError}
              onDismissSwapError={() => setSwapError(null)}
            />
          ) : (
            <p className="text-sm text-gray-500">Loading row…</p>
          )}
        </CallRowSidePanel>
        ) : null
      }
    />
  )}
</div>
  )
}
