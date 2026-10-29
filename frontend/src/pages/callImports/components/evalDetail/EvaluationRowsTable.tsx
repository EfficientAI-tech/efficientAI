import {
  AlertCircle,
  Check,
  Copy,
  Filter,
  Loader2,
  RotateCw,
  Search,
  Trash2,
  X,
  XCircle,
} from 'lucide-react'
import Pagination from '../../../../components/Pagination'
import StatusBadge from '../../../../components/shared/StatusBadge'
import DiariseStatusPill from '../../../../components/callImports/DiariseStatusPill'
import { itemsOf } from '../../../../lib/safeData'
import type { CallImportEvaluation, CallImportEvaluationRow } from '../../../../types/api'
import FilterChip from '../evalCharts/FilterChip'
import {
  ClassificationScoreSummary,
  formatClassificationScoreTooltip,
  humanizeClassificationLabel,
  type ClassificationScoreView,
} from '../../classificationScoreDisplay'
import { CallRowDetailSplitLayout } from '../CallRowDetailSplitLayout'
import { CallRowSidePanel } from '../CallRowSidePanel'
import {
  CallImportEvaluationRowSidePanelContent,
  evaluationRowHasCallFlow,
  type CallImportEvaluationRowSidePanelTabId,
} from '../CallImportEvaluationRowSidePanelContent'
import { SortableHeader } from './SortableHeader'
import type { useEvalRetryMutations } from '../../hooks/useEvalRetryMutations'

type RetryApi = ReturnType<typeof useEvalRetryMutations>

export type EvaluationRowsTableProps = {
  resultsTab: 'table' | 'visualizations' | 'flow'
  evaluation: CallImportEvaluation
  rowsQuery: {
    isLoading: boolean
    data?: {
      items?: CallImportEvaluationRow[]
      page: number
      page_size: number
      total: number
    }
  }
  detailRow: CallImportEvaluationRow | null
  setDetailRow: React.Dispatch<React.SetStateAction<CallImportEvaluationRow | null>>
  detailRowFull: CallImportEvaluationRow | null | undefined
  evalPanelTab: CallImportEvaluationRowSidePanelTabId
  setEvalPanelTab: (t: CallImportEvaluationRowSidePanelTabId) => void
  parentMetrics: {
    id: string
    name: string
    selection_mode: 'single_choice' | 'multi_label' | null
    allow_discovery: boolean
    children: { id: string; name: string }[]
  }[]
  displayMetrics: {
    id: string
    name: string
    hasRationale: boolean
  }[]
  totalPages: number
  filteredRowsSummary: string
  hasActiveFilters: boolean
  searchInput: string
  setSearchInput: (v: string) => void
  searchQuery: string
  setSearchQuery: (v: string) => void
  statusFilter: string | null
  setStatusFilter: (v: string | null) => void
  tableFilterMetricId: string
  setTableFilterMetricId: (v: string) => void
  tableFilterMetricValue: string
  setTableFilterMetricValue: (v: string) => void
  classificationTableYesNo: string
  setClassificationTableYesNo: (v: string) => void
  classificationTableChoice: string
  setClassificationTableChoice: (v: string) => void
  classificationTableLevel: string
  setClassificationTableLevel: (v: string) => void
  classificationMetricFilter: {
    metricId: string
    metricName: string
    yesNo?: string | null
    choice?: string | null
    level?: string | null
  } | null
  setClassificationMetricFilter: (v: EvaluationRowsTableProps['classificationMetricFilter']) => void
  metricFilter: { metricId: string; metricName: string; value: string } | null
  setMetricFilter: (v: EvaluationRowsTableProps['metricFilter']) => void
  flowFilter: {
    parentId: string
    parentName: string
    nodeId: string
    nodeLabel: string
    targetNodeId?: string | null
    targetNodeLabel?: string | null
  } | null
  setFlowFilter: (v: EvaluationRowsTableProps['flowFilter']) => void
  discoveredFilter: {
    parentId: string
    parentName: string
    labelKey?: string
    labelName?: string
    anyDiscovered?: boolean
  } | null
  setDiscoveredFilter: (v: EvaluationRowsTableProps['discoveredFilter']) => void
  aggregateQuery: {
    isLoading: boolean
    data?: {
      metrics: {
        metric_id: string
        classification_facets?: {
          yes_no?: { label: string; count: number }[]
          choice?: { label: string; count: number }[]
          level?: { label: string; count: number }[]
        }
        value_counts?: { label: string; count: number }[]
      }[]
    }
  }
  tableFilterMetricAggregate?: EvaluationRowsTableProps['aggregateQuery']['data'] extends infer D
    ? D extends { metrics: infer M }
      ? M extends Array<infer X>
        ? X
        : never
      : never
    : never
  tableMetricIsClassification: boolean
  tableMetricFilterValueOptions: { value: string; count: number }[]
  applyClassificationTableFilter: (
    metricId: string,
    yesNo: string,
    choice: string,
    level: string,
  ) => void
  applyTableMetricFilter: (metricId: string, value: string) => void
  sortBy: string | null
  sortDir: 'asc' | 'desc'
  handleColumnSort: (key: string) => void
  statusFilterMenuOpen: boolean
  setStatusFilterMenuOpen: (v: boolean | ((p: boolean) => boolean)) => void
  statusFilterMenuRef: React.RefObject<HTMLDivElement>
  totalMetricColumnCount: number
  getMetricLlmLabel: (metricId: string) => string
  copiedRowId: string | null
  handleCopyConversationId: (
    row: CallImportEvaluationRow,
    event: React.MouseEvent | React.KeyboardEvent,
  ) => void
  bulkOperationActive: boolean
  cancellingRowId: string | null
  cancelRowMutation: { mutate: (rowId: string) => void }
  retry: RetryApi
  pendingDeleteRow: CallImportEvaluationRow | null
  setPendingDeleteRow: (row: CallImportEvaluationRow | null) => void
  deleteRowMutation: { isPending: boolean }
  formatDateTime: (value: string | null | undefined) => string
  formatRecordingDate: (value: string | null | undefined) => string
  setRowDeleteError: (msg: string | null) => void
  setPage: (fn: (p: number) => number) => void
}

export function EvaluationRowsTable(props: EvaluationRowsTableProps) {
  if (props.resultsTab !== 'table') return null
  const {
    evaluation,
    rowsQuery,
    detailRow,
    setDetailRow,
    detailRowFull,
    evalPanelTab,
    setEvalPanelTab,
    parentMetrics,
    displayMetrics,
    totalPages,
    filteredRowsSummary,
    hasActiveFilters,
    searchInput,
    setSearchInput,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    tableFilterMetricId,
    setTableFilterMetricId,
    tableFilterMetricValue,
    setTableFilterMetricValue,
    classificationTableYesNo,
    setClassificationTableYesNo,
    classificationTableChoice,
    setClassificationTableChoice,
    classificationTableLevel,
    setClassificationTableLevel,
    classificationMetricFilter,
    setClassificationMetricFilter,
    metricFilter,
    setMetricFilter,
    flowFilter,
    setFlowFilter,
    discoveredFilter,
    setDiscoveredFilter,
    aggregateQuery,
    tableFilterMetricAggregate,
    tableMetricIsClassification,
    tableMetricFilterValueOptions,
    applyClassificationTableFilter,
    applyTableMetricFilter,
    sortBy,
    sortDir,
    handleColumnSort,
    statusFilterMenuOpen,
    setStatusFilterMenuOpen,
    statusFilterMenuRef,
    totalMetricColumnCount,
    getMetricLlmLabel,
    copiedRowId,
    handleCopyConversationId,
    bulkOperationActive,
    cancellingRowId,
    cancelRowMutation,
    retry,
    pendingDeleteRow,
    setPendingDeleteRow,
    deleteRowMutation,
    formatDateTime,
    formatRecordingDate,
    setRowDeleteError,
    setPage,
  } = props
  const { retryRowMutation, pendingRetryRowId } = retry
  return (
    <>
            <div className="mb-3 flex items-stretch gap-2 flex-wrap">
              <div className="relative flex-1 min-w-[260px]">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                <input
                  type="text"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  placeholder="Search by Conversation ID or transcript…"
                  className="w-full pl-9 pr-9 py-2 text-sm border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500"
                />
                {searchInput && (
                  <button
                    type="button"
                    onClick={() => setSearchInput('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                    aria-label="Clear search"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              <select
                value={statusFilter ?? ''}
                onChange={(e) => setStatusFilter(e.target.value || null)}
                className="px-3 py-2 text-sm border border-gray-300 rounded-md shadow-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500"
              >
                <option value="">All statuses</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="pending">Pending</option>
                <option value="running">Running</option>
                <option value="skipped">Skipped</option>
              </select>
              <select
                value={tableFilterMetricId}
                onChange={(e) => {
                  const nextId = e.target.value
                  setTableFilterMetricId(nextId)
                  setTableFilterMetricValue('')
                  setClassificationTableYesNo('')
                  setClassificationTableChoice('')
                  setClassificationTableLevel('')
                  setClassificationMetricFilter(null)
                  setMetricFilter(null)
                  if (!nextId || !flowFilter?.targetNodeId) {
                    setFlowFilter(null)
                  }
                }}
                className="min-w-[160px] max-w-[220px] px-3 py-2 text-sm border border-gray-300 rounded-md shadow-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500"
                title="Filter rows by a metric value"
              >
                <option value="">All metrics</option>
                {displayMetrics.map((metric) => (
                  <option key={metric.id} value={metric.id}>
                    {metric.name}
                  </option>
                ))}
              </select>
              {tableFilterMetricId && tableMetricIsClassification ? (
                <>
                  {tableFilterMetricAggregate?.classification_facets?.yes_no
                    ?.length ? (
                    <select
                      value={classificationTableYesNo}
                      onChange={(e) => {
                        const next = e.target.value
                        setClassificationTableYesNo(next)
                        applyClassificationTableFilter(
                          tableFilterMetricId,
                          next,
                          classificationTableChoice,
                          classificationTableLevel,
                        )
                      }}
                      disabled={aggregateQuery.isLoading}
                      className="min-w-[120px] px-3 py-2 text-sm border border-gray-300 rounded-md shadow-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500 disabled:bg-gray-50"
                      title="Filter by Yes/No"
                    >
                      <option value="">All Yes/No</option>
                      {tableFilterMetricAggregate.classification_facets.yes_no.map(
                        (vc) => (
                          <option key={vc.label} value={vc.label}>
                            {vc.label} ({vc.count})
                          </option>
                        ),
                      )}
                    </select>
                  ) : null}
                  {tableFilterMetricAggregate?.classification_facets?.choice
                    ?.length ? (
                    <select
                      value={classificationTableChoice}
                      onChange={(e) => {
                        const next = e.target.value
                        setClassificationTableChoice(next)
                        applyClassificationTableFilter(
                          tableFilterMetricId,
                          classificationTableYesNo,
                          next,
                          classificationTableLevel,
                        )
                      }}
                      disabled={aggregateQuery.isLoading}
                      className="min-w-[160px] max-w-[280px] px-3 py-2 text-sm border border-gray-300 rounded-md shadow-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500 disabled:bg-gray-50"
                      title="Filter by category"
                    >
                      <option value="">All categories</option>
                      {tableFilterMetricAggregate.classification_facets.choice.map(
                        (vc) => (
                          <option key={vc.label} value={vc.label}>
                            {humanizeClassificationLabel(vc.label)} ({vc.count})
                          </option>
                        ),
                      )}
                    </select>
                  ) : null}
                  {tableFilterMetricAggregate?.classification_facets?.level
                    ?.length ? (
                    <select
                      value={classificationTableLevel}
                      onChange={(e) => {
                        const next = e.target.value
                        setClassificationTableLevel(next)
                        applyClassificationTableFilter(
                          tableFilterMetricId,
                          classificationTableYesNo,
                          classificationTableChoice,
                          next,
                        )
                      }}
                      disabled={aggregateQuery.isLoading}
                      className="min-w-[140px] max-w-[220px] px-3 py-2 text-sm border border-gray-300 rounded-md shadow-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500 disabled:bg-gray-50"
                      title="Filter by level"
                    >
                      <option value="">All levels</option>
                      {tableFilterMetricAggregate.classification_facets.level.map(
                        (vc) => (
                          <option key={vc.label} value={vc.label}>
                            {vc.label} ({vc.count})
                          </option>
                        ),
                      )}
                    </select>
                  ) : null}
                </>
              ) : tableFilterMetricId ? (
                tableMetricFilterValueOptions.length > 0 ? (
                  <select
                    value={tableFilterMetricValue}
                    onChange={(e) => {
                      const nextValue = e.target.value
                      setTableFilterMetricValue(nextValue)
                      if (nextValue) {
                        applyTableMetricFilter(tableFilterMetricId, nextValue)
                      }
                    }}
                    disabled={aggregateQuery.isLoading}
                    className="min-w-[140px] max-w-[240px] px-3 py-2 text-sm border border-gray-300 rounded-md shadow-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500 disabled:bg-gray-50"
                    title="Metric value to match"
                  >
                    <option value="">
                      {aggregateQuery.isLoading
                        ? 'Loading values…'
                        : 'Select value…'}
                    </option>
                    {tableMetricFilterValueOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.value} ({opt.count})
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={tableFilterMetricValue}
                    onChange={(e) => setTableFilterMetricValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        applyTableMetricFilter(
                          tableFilterMetricId,
                          tableFilterMetricValue,
                        )
                      }
                    }}
                    placeholder={
                      aggregateQuery.isLoading
                        ? 'Loading…'
                        : 'Metric value (Enter to apply)'
                    }
                    className="min-w-[160px] px-3 py-2 text-sm border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500"
                  />
                )
              ) : null}
            </div>

            {hasActiveFilters && (
              <div className="mb-3 flex items-center gap-1.5 flex-wrap text-xs">
                <span className="inline-flex items-center gap-1 text-gray-500">
                  <Filter className="h-3.5 w-3.5" />
                  Active filters:
                </span>
                {searchQuery && (
                  <FilterChip
                    label={`Search: "${searchQuery}"`}
                    onClear={() => {
                      setSearchInput('')
                      setSearchQuery('')
                    }}
                  />
                )}
                {statusFilter && (
                  <FilterChip
                    label={`Status: ${statusFilter}`}
                    onClear={() => setStatusFilter(null)}
                  />
                )}
                {metricFilter && (
                  <FilterChip
                    label={`${metricFilter.metricName} = ${metricFilter.value}`}
                    onClear={() => setMetricFilter(null)}
                  />
                )}
                {classificationMetricFilter?.yesNo && (
                  <FilterChip
                    label={`${classificationMetricFilter.metricName} · Yes/No: ${classificationMetricFilter.yesNo}`}
                    onClear={() => {
                      setClassificationTableYesNo('')
                      applyClassificationTableFilter(
                        classificationMetricFilter.metricId,
                        '',
                        classificationTableChoice,
                        classificationTableLevel,
                      )
                    }}
                  />
                )}
                {classificationMetricFilter?.choice && (
                  <FilterChip
                    label={`${classificationMetricFilter.metricName} · Category: ${humanizeClassificationLabel(classificationMetricFilter.choice)}`}
                    onClear={() => {
                      setClassificationTableChoice('')
                      applyClassificationTableFilter(
                        classificationMetricFilter.metricId,
                        classificationTableYesNo,
                        '',
                        classificationTableLevel,
                      )
                    }}
                  />
                )}
                {classificationMetricFilter?.level && (
                  <FilterChip
                    label={`${classificationMetricFilter.metricName} · Level: ${classificationMetricFilter.level}`}
                    onClear={() => {
                      setClassificationTableLevel('')
                      applyClassificationTableFilter(
                        classificationMetricFilter.metricId,
                        classificationTableYesNo,
                        classificationTableChoice,
                        '',
                      )
                    }}
                  />
                )}
                {flowFilter && (
                  <FilterChip
                    label={
                      flowFilter.targetNodeId
                        ? `${flowFilter.parentName}: ${flowFilter.nodeLabel} → ${flowFilter.targetNodeLabel}`
                        : `${flowFilter.parentName}: passed through "${flowFilter.nodeLabel}"`
                    }
                    onClear={() => setFlowFilter(null)}
                  />
                )}
                {discoveredFilter && (
                  <FilterChip
                    label={
                      discoveredFilter.anyDiscovered
                        ? `${discoveredFilter.parentName}: any LLM-discovered metric`
                        : `${discoveredFilter.parentName}: discovered "${
                            discoveredFilter.labelName ||
                            discoveredFilter.labelKey
                          }"`
                    }
                    onClear={() => setDiscoveredFilter(null)}
                  />
                )}
                <button
                  type="button"
                  onClick={() => {
                    setSearchInput('')
                    setSearchQuery('')
                    setStatusFilter(null)
                    setMetricFilter(null)
                    setClassificationMetricFilter(null)
                    setClassificationTableYesNo('')
                    setClassificationTableChoice('')
                    setClassificationTableLevel('')
                    setFlowFilter(null)
                    setDiscoveredFilter(null)
                    setTableFilterMetricId('')
                    setTableFilterMetricValue('')
                  }}
                  className="ml-1 text-gray-500 underline underline-offset-2 hover:text-gray-700"
                >
                  Clear all
                </button>
              </div>
            )}

        {rowsQuery.isLoading ? (
          <p className="text-sm text-gray-500">Loading rows…</p>
        ) : !rowsQuery.data?.items?.length ? (
          hasActiveFilters ? (
            <div className="text-sm text-gray-500 border border-dashed border-gray-300 rounded-md p-6 text-center">
              No rows match the current filters.{' '}
              <button
                type="button"
                onClick={() => {
                  setSearchInput('')
                  setSearchQuery('')
                  setStatusFilter(null)
                  setMetricFilter(null)
                  setClassificationMetricFilter(null)
                  setClassificationTableYesNo('')
                  setClassificationTableChoice('')
                  setClassificationTableLevel('')
                  setFlowFilter(null)
                  setDiscoveredFilter(null)
                  setTableFilterMetricId('')
                  setTableFilterMetricValue('')
                }}
                className="text-primary-600 hover:text-primary-700 underline underline-offset-2"
              >
                Clear filters
              </button>
            </div>
          ) : (
            <p className="text-sm text-gray-500">
              No row results yet. Rows will appear as workers complete them.
            </p>
          )
        ) : (
          <CallRowDetailSplitLayout
            panelOpen={!!(detailRow && evaluation)}
            list={
            <div className="min-w-0">
            {totalMetricColumnCount > 3 && (
              <p className="mb-2 text-[11px] text-gray-500">
                Scroll the table horizontally to see all{' '}
                {totalMetricColumnCount} metric columns.
              </p>
            )}
            {/* Top pagination mirrors the bottom controls so the user
                doesn't have to scroll past every row to flip pages. */}
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-gray-600">
              <span>{filteredRowsSummary}</span>
              {hasActiveFilters && rowsQuery.data ? (
                <span className="text-gray-500">
                  Page {rowsQuery.data.page} of {totalPages}
                </span>
              ) : null}
            </div>
            <Pagination
              page={rowsQuery.data.page}
              pageCount={totalPages}
              total={rowsQuery.data.total}
              pageSize={rowsQuery.data.page_size}
              className="mb-2"
              onPrev={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => p + 1)}
            />
            <div className="overflow-x-auto border border-gray-100 rounded">
              <table className="min-w-max w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <SortableHeader
                      columnKey="row_index"
                      activeKey={sortBy}
                      activeDir={sortDir}
                      onCycle={handleColumnSort}
                      title="Row index"
                      className="sticky left-0 z-10 bg-gray-50"
                    >
                      #
                    </SortableHeader>
                    <SortableHeader
                      columnKey="conversation_id"
                      activeKey={sortBy}
                      activeDir={sortDir}
                      onCycle={handleColumnSort}
                    >
                      Conversation ID
                    </SortableHeader>
                    <SortableHeader
                      columnKey="status"
                      activeKey={sortBy}
                      activeDir={sortDir}
                      onCycle={handleColumnSort}
                      rightSlot={
                        <div className="relative" ref={statusFilterMenuRef}>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              setStatusFilterMenuOpen((v) => !v)
                            }}
                            className={
                              'p-1 rounded hover:bg-gray-200 transition-colors ' +
                              (statusFilter
                                ? 'text-primary-600'
                                : 'text-gray-400')
                            }
                            title={
                              statusFilter
                                ? `Status filter: ${statusFilter} (click to change)`
                                : 'Filter by status'
                            }
                            aria-label="Filter by status"
                          >
                            <Filter className="h-3 w-3" />
                          </button>
                          {statusFilterMenuOpen && (
                            <div
                              role="menu"
                              className="absolute left-0 top-full z-30 mt-1 w-40 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden text-xs"
                            >
                              {[
                                { value: '', label: 'All statuses' },
                                { value: 'completed', label: 'Completed' },
                                { value: 'failed', label: 'Failed' },
                                { value: 'pending', label: 'Pending' },
                                { value: 'running', label: 'Running' },
                                { value: 'skipped', label: 'Skipped' },
                              ].map((opt) => {
                                const isCurrent =
                                  (statusFilter ?? '') === opt.value
                                return (
                                  <button
                                    key={opt.value || '__all'}
                                    type="button"
                                    role="menuitem"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      setStatusFilter(opt.value || null)
                                      setStatusFilterMenuOpen(false)
                                    }}
                                    className={
                                      'w-full px-3 py-1.5 text-left normal-case font-normal hover:bg-gray-50 flex items-center justify-between ' +
                                      (isCurrent
                                        ? 'text-primary-700'
                                        : 'text-gray-700')
                                    }
                                  >
                                    <span>{opt.label}</span>
                                    {isCurrent && (
                                      <Check className="h-3 w-3" />
                                    )}
                                  </button>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      }
                    >
                      Status
                    </SortableHeader>
                    {displayMetrics.flatMap((metric) => {
                      const llmLabel = getMetricLlmLabel(metric.id)
                      const headers = [
                        <SortableHeader
                          key={metric.id}
                          columnKey={`metric:${metric.id}`}
                          activeKey={sortBy}
                          activeDir={sortDir}
                          onCycle={handleColumnSort}
                          title={metric.name}
                        >
                          <span className="flex flex-col items-start leading-tight normal-case">
                            <span className="truncate max-w-[220px] text-xs font-medium text-gray-700">
                              {metric.name}
                            </span>
                            <span className="text-[10px] font-normal text-gray-400 mt-0.5">
                              {llmLabel}
                            </span>
                          </span>
                        </SortableHeader>,
                      ]
                      if (metric.hasRationale) {
                        headers.push(
                          <th
                            key={`${metric.id}__rationale`}
                            className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
                            title={`${metric.name} - LLM Rationale`}
                          >
                            <span className="flex flex-col items-start leading-tight normal-case">
                              <span className="text-xs font-medium text-gray-700">
                                {metric.name}{' '}
                                <span className="text-gray-400">- LLM Rationale</span>
                              </span>
                              <span className="text-[10px] font-normal text-gray-400 mt-0.5">
                                {llmLabel}
                              </span>
                            </span>
                          </th>,
                        )
                      }
                      return headers
                    })}
                    <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase whitespace-nowrap">
                      &nbsp;
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {itemsOf<CallImportEvaluationRow>(rowsQuery.data).map((row) => (
                      <tr
                        key={row.id}
                        onClick={() => {
                          setDetailRow((prev) => {
                            if (prev?.id === row.id) return null
                            setEvalPanelTab('scores')
                            return row
                          })
                        }}
                        className={`hover:bg-primary-50/40 cursor-pointer transition ${
                          detailRow?.id === row.id ? 'bg-primary-50/60' : ''
                        }`}
                      >
                        <td className="sticky left-0 z-10 bg-inherit px-3 py-2 text-sm text-gray-600 whitespace-nowrap">
                          {(row.row_index ?? 0) + 1}
                        </td>
                        {/*
                          Conversation ID stays selectable; row click opens
                          the docked panel. Copy stops propagation only.
                         */}
                        <td className="px-3 py-2 text-sm font-mono text-primary-700 whitespace-nowrap">
                          {row.conversation_id ? (
                            <span className="inline-flex items-center gap-2">
                              <span
                                className="select-text cursor-text"
                                title={row.conversation_id}
                              >
                                {row.conversation_id}
                              </span>
                              <button
                                type="button"
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
                                onClick={(e) =>
                                  handleCopyConversationId(row, e)
                                }
                                onMouseDown={(e) => e.stopPropagation()}
                                className={`inline-flex items-center justify-center w-6 h-6 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 ${
                                  copiedRowId === row.id
                                    ? 'text-green-600 bg-green-50'
                                    : 'text-gray-400 hover:text-primary-700 hover:bg-primary-50'
                                }`}
                              >
                                {copiedRowId === row.id ? (
                                  <Check className="h-3.5 w-3.5" />
                                ) : (
                                  <Copy className="h-3.5 w-3.5" />
                                )}
                              </button>
                            </span>
                          ) : (
                            '-'
                          )}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          <div className="inline-flex items-center gap-1.5 flex-wrap">
                            <StatusBadge status={row.status} size="sm" />
                            <DiariseStatusPill
                              status={row.diarised_transcript_status}
                            />
                          </div>
                        </td>
                        {displayMetrics.flatMap((metric) => {
                          const score = row.metric_scores?.[metric.id]
                          const value =
                            score && typeof score === 'object'
                              ? score.value
                              : undefined
                          const scoreType =
                            score &&
                            typeof score === 'object' &&
                            typeof score.type === 'string'
                              ? score.type.toLowerCase()
                              : undefined
                          const isClassificationRow =
                            score &&
                            typeof score === 'object' &&
                            typeof (score as { type?: string }).type === 'string' &&
                            (score as { type: string }).type.toLowerCase() ===
                              'classification'
                          const isEmpty =
                            !score ||
                            (!isClassificationRow &&
                              (value === undefined ||
                                value === null ||
                                value === ''))
                          const valueStr = isEmpty ? '' : String(value)
                          const isLongText =
                            scoreType === 'text' && valueStr.length > 80
                          const errorText =
                            score &&
                            typeof score === 'object' &&
                            score.error
                              ? String(score.error)
                              : undefined
                          // ``rationale`` is only populated for metrics that
                          // were scored with capture_rationale=true. When
                          // ``metric.hasRationale`` is true we render the
                          // rationale in its own adjacent column (mirroring
                          // the CSV export), otherwise we omit the column
                          // entirely so other metrics stay compact.
                          const rationale =
                            score &&
                            typeof score === 'object' &&
                            typeof (score as { rationale?: unknown })
                              .rationale === 'string' &&
                            (score as { rationale?: string }).rationale
                              ? String(
                                  (score as { rationale: string }).rationale,
                                )
                              : undefined
                          const isClassification =
                            scoreType === 'classification' || isClassificationRow
                          const classificationTooltip =
                            isClassification &&
                            score &&
                            typeof score === 'object'
                              ? formatClassificationScoreTooltip(
                                  score as ClassificationScoreView,
                                )
                              : undefined
                          const valueTooltip =
                            errorText ||
                            classificationTooltip ||
                            (isLongText ? valueStr : undefined)
                          const valueCellClassName =
                            scoreType === 'text'
                              ? 'px-3 py-2 text-sm text-gray-700 align-top max-w-xs'
                              : isClassification
                                ? 'px-3 py-2 text-sm text-gray-700 align-top whitespace-normal min-w-[9rem] max-w-[16rem]'
                                : 'px-3 py-2 text-sm text-gray-700 whitespace-nowrap'
                          const cells = [
                            <td
                              key={metric.id}
                              className={valueCellClassName}
                              title={valueTooltip}
                            >
                              {isEmpty ? (
                                '-'
                              ) : isClassification &&
                                score &&
                                typeof score === 'object' ? (
                                <ClassificationScoreSummary
                                  score={score as ClassificationScoreView}
                                />
                              ) : scoreType === 'text' ? (
                                <span className="block whitespace-pre-wrap break-words leading-snug line-clamp-3">
                                  {valueStr}
                                </span>
                              ) : (
                                <span className="font-medium">{valueStr}</span>
                              )}
                            </td>,
                          ]
                          if (metric.hasRationale) {
                            cells.push(
                              <td
                                key={`${metric.id}__rationale`}
                                className="px-3 py-2 text-sm text-gray-600 align-top max-w-xs"
                                title={rationale || undefined}
                              >
                                {rationale ? (
                                  <span className="block whitespace-pre-wrap break-words leading-snug line-clamp-3">
                                    {rationale}
                                  </span>
                                ) : (
                                  <span className="text-gray-300">-</span>
                                )}
                              </td>,
                            )
                          }
                          return cells
                        })}
                        <td className="px-3 py-2 text-right whitespace-nowrap">
                          <div className="inline-flex items-center gap-1">
                            {(row.status === 'pending' ||
                              row.status === 'running') && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  if (bulkOperationActive || cancellingRowId) {
                                    return
                                  }
                                  cancelRowMutation.mutate(row.id)
                                }}
                                disabled={
                                  bulkOperationActive ||
                                  (cancellingRowId !== null &&
                                    cancellingRowId !== row.id)
                                }
                                className="p-1.5 rounded text-gray-400 hover:text-amber-700 hover:bg-amber-50 transition-colors disabled:opacity-40"
                                title={
                                  bulkOperationActive
                                    ? 'Wait for the current bulk operation to finish'
                                    : 'Abort this row'
                                }
                                aria-label="Abort evaluation row"
                              >
                                {cancellingRowId === row.id ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <XCircle className="h-4 w-4" />
                                )}
                              </button>
                            )}
                            {row.status === 'failed' && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  if (bulkOperationActive || pendingRetryRowId) {
                                    return
                                  }
                                  retryRowMutation.mutate(row.id)
                                }}
                                disabled={
                                  bulkOperationActive ||
                                  (pendingRetryRowId !== null &&
                                    pendingRetryRowId !== row.id)
                                }
                                className="p-1.5 rounded text-gray-400 hover:text-amber-700 hover:bg-amber-50 transition-colors disabled:opacity-40"
                                title={
                                  bulkOperationActive
                                    ? 'Wait for the current bulk operation to finish'
                                    : 'Retry evaluation on this row'
                                }
                                aria-label="Retry evaluation row"
                              >
                                {pendingRetryRowId === row.id ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <RotateCw className="h-4 w-4" />
                                )}
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                setRowDeleteError(null)
                                setPendingDeleteRow(row)
                              }}
                              disabled={
                                deleteRowMutation.isPending &&
                                pendingDeleteRow?.id === row.id
                              }
                              className="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40"
                              title="Delete row from this evaluation"
                              aria-label="Delete evaluation row"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>

            <Pagination
              page={rowsQuery.data.page}
              pageCount={totalPages}
              total={rowsQuery.data.total}
              pageSize={rowsQuery.data.page_size}
              className="mt-3"
              onPrev={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => p + 1)}
            />
            </div>
            }
            panel={
              detailRow && evaluation ? (
              <CallRowSidePanel
                onClose={() => setDetailRow(null)}
                title={
                  detailRow.conversation_id ||
                  `Row ${(detailRow.row_index ?? 0) + 1}`
                }
                headerMeta={
                  <>
                    <StatusBadge status={detailRow.status} size="sm" />
                    <DiariseStatusPill status={detailRow.diarised_transcript_status} />
                    {detailRow.row_index !== null && (
                      <span className="text-xs text-gray-500">
                        Row #{(detailRow.row_index ?? 0) + 1}
                      </span>
                    )}
                    {detailRow.recording_date ? (
                      <span className="text-xs text-gray-500">
                        · Recorded {formatRecordingDate(detailRow.recording_date)}
                      </span>
                    ) : null}
                    {detailRow.finished_at ? (
                      <span className="text-xs text-gray-500">
                        · Finished {formatDateTime(detailRow.finished_at)}
                      </span>
                    ) : null}
                  </>
                }
                errorBanner={
                  detailRow.error_message ? (
                    <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-800 flex items-start gap-2">
                      <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                      <span>{detailRow.error_message}</span>
                    </div>
                  ) : undefined
                }
                recordingS3Key={detailRow.recording_s3_key}
                recordingUrl={detailRow.recording_url}
                tabs={(() => {
                  const scoredSource = (
                    evaluation.transcript_source || 'diarised'
                  ).toLowerCase()
                  const tabs: {
                    id: string
                    label: string
                    hint?: string
                  }[] = [
                    {
                      id: 'production',
                      label: 'Production',
                      hint: scoredSource === 'production' ? 'Scored' : undefined,
                    },
                    {
                      id: 'diarised',
                      label: 'Diarised',
                      hint: scoredSource === 'diarised' ? 'Scored' : undefined,
                    },
                    { id: 'scores', label: 'Scores' },
                  ]
                  if (evaluationRowHasCallFlow(detailRow, parentMetrics)) {
                    tabs.push({ id: 'flow', label: 'Call flow' })
                  }
                  tabs.push({ id: 'metadata', label: 'Metadata' })
                  return tabs
                })()}
                activeTab={evalPanelTab}
                onTabChange={(tabId) =>
                  setEvalPanelTab(tabId as CallImportEvaluationRowSidePanelTabId)
                }
              >
                {detailRowFull ? (
                  <CallImportEvaluationRowSidePanelContent
                    row={detailRowFull}
                    activeTab={evalPanelTab}
                    displayMetrics={displayMetrics}
                    parentMetrics={parentMetrics}
                  />
                ) : (
                  <p className="text-sm text-gray-500">Loading row…</p>
                )}
              </CallRowSidePanel>
              ) : null
            }
          />
        )}

    </>
  )
}
