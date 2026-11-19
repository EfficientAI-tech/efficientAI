import { useMemo, useRef, useState } from 'react'
import { Blocks, FileAudio, FileSpreadsheet } from 'lucide-react'
import { apiClient } from '../../../../lib/api'
import { itemsOf } from '../../../../lib/safeData'
import {
  getCallImportBatchLabel,
  getCallImportRowLabel,
  getCallImportRowSubtitle,
} from '../../utils/sourceLabels'
import type { CallImportTag } from '../../../../types/api'
import {
  buildStudioSources,
  filterImportBatches,
  matchesRecordingSearch,
  matchesSimulatedSearch,
  type StudioImportKindTab,
  type StudioRecordingRow,
  type StudioSimulatedRow,
} from './studioRunSelection'

type SourceTab = 'imports' | 'recordings' | 'simulated'

type StudioWizardCallsStepProps = {
  sourceTab: SourceTab
  onSourceTabChange: (tab: SourceTab) => void
  importsData: unknown
  importKindTab: StudioImportKindTab
  onImportKindTabChange: (tab: StudioImportKindTab) => void
  importDatasets: string[]
  importTags: CallImportTag[]
  importDatasetFilter: string
  onImportDatasetFilterChange: (value: string) => void
  importTagFilter: string[]
  onImportTagFilterChange: (value: string[]) => void
  importBatchSearch: string
  onImportBatchSearchChange: (value: string) => void
  selectedImportId: string
  onSelectedImportIdChange: (id: string) => void
  importRowSearch: string
  onImportRowSearchChange: (value: string) => void
  importRows: Array<{
    id: string
    conversation_id?: string | null
    row_index?: number | null
    recording_s3_key?: string | null
  }>
  importRowsLoading: boolean
  filteredTotalRows?: number
  selectedImportRowIds: Set<string>
  onSelectedImportRowIdsChange: (next: Set<string>) => void
  recordings: StudioRecordingRow[]
  recordingSearch: string
  onRecordingSearchChange: (value: string) => void
  selectedRecordingIds: Set<string>
  onSelectedRecordingIdsChange: (next: Set<string>) => void
  simulatedItems: StudioSimulatedRow[]
  simulatedSearch: string
  onSimulatedSearchChange: (value: string) => void
  selectedSimulatedIds: Set<string>
  onSelectedSimulatedIdsChange: (next: Set<string>) => void
}

export default function StudioWizardCallsStep({
  sourceTab,
  onSourceTabChange,
  importsData,
  importKindTab,
  onImportKindTabChange,
  importDatasets,
  importTags,
  importDatasetFilter,
  onImportDatasetFilterChange,
  importTagFilter,
  onImportTagFilterChange,
  importBatchSearch,
  onImportBatchSearchChange,
  selectedImportId,
  onSelectedImportIdChange,
  importRowSearch,
  onImportRowSearchChange,
  importRows,
  importRowsLoading,
  filteredTotalRows,
  selectedImportRowIds,
  onSelectedImportRowIdsChange,
  recordings,
  recordingSearch,
  onRecordingSearchChange,
  selectedRecordingIds,
  onSelectedRecordingIdsChange,
  simulatedItems,
  simulatedSearch,
  onSimulatedSearchChange,
  selectedSimulatedIds,
  onSelectedSimulatedIdsChange,
}: StudioWizardCallsStepProps) {
  const batches = useMemo(
    () =>
      filterImportBatches(
        itemsOf<{
          id: string
          original_filename?: string | null
          name?: string | null
          dataset?: string | null
          tags?: CallImportTag[]
        }>(importsData),
        importBatchSearch,
      ),
    [importsData, importBatchSearch],
  )

  const filteredRecordings = useMemo(
    () => recordings.filter((r) => matchesRecordingSearch(r, recordingSearch)),
    [recordings, recordingSearch],
  )

  const filteredSimulated = useMemo(
    () => simulatedItems.filter((item) => matchesSimulatedSearch(item, simulatedSearch)),
    [simulatedItems, simulatedSearch],
  )

  const selectedSources = buildStudioSources({
    selectedImportRowIds,
    selectedRecordingIds,
    selectedSimulatedIds,
    importRows,
    recordings,
    simulatedItems,
  })

  const toggleRow = (rowId: string) => {
    const next = new Set(selectedImportRowIds)
    if (next.has(rowId)) next.delete(rowId)
    else next.add(rowId)
    onSelectedImportRowIdsChange(next)
  }

  const selectedImportIdRef = useRef(selectedImportId)
  selectedImportIdRef.current = selectedImportId
  const selectedImportRowIdsRef = useRef(selectedImportRowIds)
  selectedImportRowIdsRef.current = selectedImportRowIds

  const selectAllVisibleRows = () => {
    const next = new Set(selectedImportRowIds)
    for (const row of importRows) next.add(row.id)
    onSelectedImportRowIdsChange(next)
  }

  const selectAllMatchingSearch = async () => {
    if (!selectedImportId) return
    const importIdAtRequest = selectedImportId
    const q = importRowSearch.trim() || undefined
    const { ids } = await apiClient.listCallImportRowIds(importIdAtRequest, { q })
    if (selectedImportIdRef.current !== importIdAtRequest) return
    const next = new Set(selectedImportRowIdsRef.current)
    for (const id of ids) next.add(id)
    onSelectedImportRowIdsChange(next)
  }

  const clearAllSelections = () => {
    onSelectedImportRowIdsChange(new Set())
    onSelectedRecordingIdsChange(new Set())
    onSelectedSimulatedIdsChange(new Set())
  }

  const [bulkSelecting, setBulkSelecting] = useState(false)

  const handleSelectAllMatching = () => {
    setBulkSelecting(true)
    selectAllMatchingSearch()
      .catch(() => undefined)
      .finally(() => setBulkSelecting(false))
  }

  const sourceTabs = (
    [
      { id: 'imports' as const, label: 'Call Imports' },
      { id: 'recordings' as const, label: 'Recordings' },
      { id: 'simulated' as const, label: 'Simulated' },
    ] as const
  )

  const importKindTabs = (
    [
      { id: 'datasets' as const, label: 'CSV / Dataset', icon: FileSpreadsheet },
      { id: 'audio' as const, label: 'Manual upload', icon: FileAudio },
      { id: 'platform' as const, label: 'Existing platforms', icon: Blocks },
    ] as const
  )

  return (
    <div className="flex flex-col h-full min-h-0 gap-4">
      <div className="flex justify-center shrink-0">
        <div className="inline-flex rounded-md border border-gray-200 bg-gray-50 p-0.5 text-xs font-medium w-full max-w-xl">
          {sourceTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onSourceTabChange(tab.id)}
              className={`flex-1 px-2 py-2 rounded text-center ${
                sourceTab === tab.id
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {sourceTab === 'imports' && (
        <div className="flex justify-center shrink-0">
          <div className="inline-flex flex-wrap justify-center gap-1 rounded-lg border border-gray-200 bg-white p-1 w-full max-w-2xl">
            {importKindTabs.map((tab) => {
              const Icon = tab.icon
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => onImportKindTabChange(tab.id)}
                  className={`flex items-center justify-center gap-1.5 flex-1 min-w-[7rem] px-2 py-2 rounded-md text-xs font-medium transition-colors ${
                    importKindTab === tab.id
                      ? 'bg-primary-50 text-primary-700'
                      : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                  }`}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span className="truncate">{tab.label}</span>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {sourceTab === 'imports' && (
        <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-[minmax(220px,280px)_1fr] gap-4 max-w-5xl w-full mx-auto">
          <div className="flex flex-col min-h-0 gap-2">
            <div className="space-y-2 shrink-0">
              <div className="flex items-center gap-2">
                <label htmlFor="studio-import-dataset" className="text-xs text-gray-600 shrink-0">
                  Dataset
                </label>
                <select
                  id="studio-import-dataset"
                  value={importDatasetFilter}
                  onChange={(e) => onImportDatasetFilterChange(e.target.value)}
                  className="flex-1 min-w-0 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                >
                  <option value="">All datasets</option>
                  {importDatasets.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </div>
              {importTags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {importTags.map((tag) => {
                    const active = importTagFilter.includes(tag.id)
                    return (
                      <button
                        key={tag.id}
                        type="button"
                        onClick={() =>
                          onImportTagFilterChange(
                            active
                              ? importTagFilter.filter((id) => id !== tag.id)
                              : [...importTagFilter, tag.id],
                          )
                        }
                        className={`px-2 py-0.5 text-[10px] rounded-full border transition-colors ${
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
                  {importTagFilter.length > 0 && (
                    <button
                      type="button"
                      onClick={() => onImportTagFilterChange([])}
                      className="text-[10px] text-gray-500 underline"
                    >
                      Clear tags
                    </button>
                  )}
                </div>
              )}
            </div>
            <input
              type="search"
              value={importBatchSearch}
              onChange={(e) => onImportBatchSearchChange(e.target.value)}
              placeholder="Search batches, dataset, or tag…"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shrink-0"
            />
            <ul className="flex-1 min-h-0 overflow-y-auto border border-gray-200 rounded-lg divide-y divide-gray-100">
              {batches.length === 0 ? (
                <li className="p-3 text-sm text-gray-500">No matching batches.</li>
              ) : (
                batches.map((imp: any) => (
                  <li key={imp.id}>
                    <button
                      type="button"
                      onClick={() => onSelectedImportIdChange(imp.id)}
                      className={`w-full text-left px-3 py-2.5 text-sm hover:bg-gray-50 ${
                        selectedImportId === imp.id ? 'bg-primary-50 text-primary-900' : 'text-gray-800'
                      }`}
                    >
                      <span className="block font-medium truncate">{getCallImportBatchLabel(imp)}</span>
                      <span className="block text-xs text-gray-500 truncate">
                        {[imp.dataset, ...(imp.tags ?? []).map((t: CallImportTag) => t.name)]
                          .filter(Boolean)
                          .join(' · ') || imp.id.slice(0, 8)}
                      </span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          </div>

          <div className="flex flex-col min-h-0 gap-2">
            {!selectedImportId ? (
              <p className="text-sm text-gray-500">Select an import batch to choose rows.</p>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="search"
                    value={importRowSearch}
                    onChange={(e) => onImportRowSearchChange(e.target.value)}
                    placeholder="Search conversation ID or row UUID…"
                    className="flex-1 min-w-[200px] rounded-md border border-gray-300 px-3 py-2 text-sm"
                  />
                  <button
                    type="button"
                    onClick={selectAllVisibleRows}
                    disabled={importRows.length === 0}
                    className="text-xs font-medium text-primary-700 hover:text-primary-900 disabled:opacity-50"
                  >
                    Select visible
                  </button>
                  <button
                    type="button"
                    onClick={handleSelectAllMatching}
                    disabled={bulkSelecting}
                    className="text-xs font-medium text-primary-700 hover:text-primary-900 disabled:opacity-50"
                  >
                    {bulkSelecting ? 'Selecting…' : 'Select all matching'}
                  </button>
                </div>
                {typeof filteredTotalRows === 'number' && (
                  <p className="text-xs text-gray-500">
                    Showing {importRows.length} row(s)
                    {importRowSearch.trim() ? ` · ${filteredTotalRows} match search` : ''}
                  </p>
                )}
                <ul className="flex-1 min-h-0 overflow-y-auto border border-gray-200 rounded-lg p-2 space-y-1">
                  {importRowsLoading ? (
                    <li className="p-4 text-sm text-gray-500 text-center">Loading rows…</li>
                  ) : importRows.length === 0 ? (
                    <li className="p-4 text-sm text-gray-500 text-center">No rows match this search.</li>
                  ) : (
                    importRows.map((row) => (
                      <li key={row.id}>
                        <label className="flex items-start gap-2 text-sm py-1.5 px-1 rounded hover:bg-gray-50 cursor-pointer">
                          <input
                            type="checkbox"
                            className="mt-1"
                            checked={selectedImportRowIds.has(row.id)}
                            onChange={() => toggleRow(row.id)}
                          />
                          <span className="min-w-0">
                            <span className="block truncate font-medium text-gray-900">
                              {getCallImportRowLabel(
                                row as Parameters<typeof getCallImportRowLabel>[0],
                              )}
                            </span>
                            <span className="block text-xs text-gray-500 truncate">
                              {getCallImportRowSubtitle(
                                row as Parameters<typeof getCallImportRowSubtitle>[0],
                              )}
                            </span>
                          </span>
                        </label>
                      </li>
                    ))
                  )}
                </ul>
              </>
            )}
          </div>
        </div>
      )}

      {sourceTab === 'recordings' && (
        <div className="flex flex-col flex-1 min-h-0 gap-2 max-w-3xl w-full mx-auto">
          <input
            type="search"
            value={recordingSearch}
            onChange={(e) => onRecordingSearchChange(e.target.value)}
            placeholder="Search call short ID or label…"
            className="w-full max-w-lg rounded-md border border-gray-300 px-3 py-2 text-sm shrink-0"
          />
          <ul className="flex-1 min-h-0 overflow-y-auto border border-gray-200 rounded-lg p-2 space-y-1">
            {filteredRecordings.length === 0 ? (
              <li className="p-4 text-sm text-gray-500 text-center">No recordings match.</li>
            ) : (
              filteredRecordings.map((rec) => (
                <li key={rec.id}>
                  <label className="flex items-start gap-2 text-sm py-1.5 px-1 rounded hover:bg-gray-50 cursor-pointer">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={selectedRecordingIds.has(rec.id)}
                      onChange={() => {
                        const next = new Set(selectedRecordingIds)
                        if (next.has(rec.id)) next.delete(rec.id)
                        else next.add(rec.id)
                        onSelectedRecordingIdsChange(next)
                      }}
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-gray-900">{rec.label}</span>
                      <span className="block text-xs text-gray-500 truncate">
                        {rec.subtitle} · {rec.kind}
                      </span>
                    </span>
                  </label>
                </li>
              ))
            )}
          </ul>
        </div>
      )}

      {sourceTab === 'simulated' && (
        <div className="flex flex-col flex-1 min-h-0 gap-2 max-w-3xl w-full mx-auto">
          <input
            type="search"
            value={simulatedSearch}
            onChange={(e) => onSimulatedSearchChange(e.target.value)}
            placeholder="Search result ID or name…"
            className="w-full max-w-lg rounded-md border border-gray-300 px-3 py-2 text-sm shrink-0"
          />
          <ul className="flex-1 min-h-0 overflow-y-auto border border-gray-200 rounded-lg p-2 space-y-1">
            {filteredSimulated.length === 0 ? (
              <li className="p-4 text-sm text-gray-500 text-center">No simulated results match.</li>
            ) : (
              filteredSimulated.map((item) => (
                <li key={item.id}>
                  <label className="flex items-start gap-2 text-sm py-1.5 px-1 rounded hover:bg-gray-50 cursor-pointer">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={selectedSimulatedIds.has(item.id)}
                      onChange={() => {
                        const next = new Set(selectedSimulatedIds)
                        if (next.has(item.id)) next.delete(item.id)
                        else next.add(item.id)
                        onSelectedSimulatedIdsChange(next)
                      }}
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-gray-900">
                        {item.name?.trim() || item.result_id || item.id.slice(0, 8)}
                      </span>
                      {item.result_id && (
                        <span className="block text-xs text-gray-500 truncate">{item.result_id}</span>
                      )}
                    </span>
                  </label>
                </li>
              ))
            )}
          </ul>
        </div>
      )}

      {selectedSources.length > 0 && (
        <div className="shrink-0 border-t border-gray-100 pt-3">
          <div className="flex items-center justify-between gap-2 mb-2">
            <p className="text-xs font-medium text-gray-700">
              Selected ({selectedSources.length})
            </p>
            <button
              type="button"
              onClick={clearAllSelections}
              className="text-xs font-medium text-primary-600 hover:text-primary-700"
            >
              Clear selection
            </button>
          </div>
          <div className="flex flex-wrap gap-2 max-h-24 overflow-y-auto">
            {selectedSources.map((src) => (
              <span
                key={`${src.source_kind}:${src.source_ref}`}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-gray-100 text-xs text-gray-700"
              >
                {src.display_label}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
