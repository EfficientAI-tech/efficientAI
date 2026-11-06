import { useEffect, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { copyTextToClipboard } from '../../../lib/clipboard'
import type { CallImportRow } from '../../../types/api'
import type { CallImportRowSidePanelTabId } from '../components/CallImportRowSidePanelContent'

import {
  importRowsPollMs,
} from '../importPolling'

export const ROW_PAGE_SIZE = 100

export function getRawColumnEntries(row: CallImportRow): Array<[string, unknown]> {
  const transcriptValue = (row.transcript || '').trim()
  const recordingUrlValue = (row.recording_url || '').trim()
  const conversationIdValue = (row.conversation_id || '').trim()
  return Object.entries(row.raw_columns || {}).filter(([key, value]) => {
    if (!key.trim()) return false
    const stringValue = value === null || value === undefined ? '' : String(value)
    const trimmedValue = stringValue.trim()
    if (!trimmedValue) return true
    if (transcriptValue && trimmedValue === transcriptValue) return false
    if (recordingUrlValue && trimmedValue === recordingUrlValue) return false
    if (conversationIdValue && trimmedValue === conversationIdValue) return false
    return true
  })
}

export type DiarisedStatusFilter =
  | 'all'
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'

type HeaderData = {
  total_rows?: number
  status?: string
  source_format?: string | null
  platform_progress?: { is_active?: boolean } | null
  diarised_pending_rows?: number
  diarised_running_rows?: number
}

export function useImportDetailRows(
  id: string,
  activeWorkspaceId: string | null | undefined,
  headerData: HeaderData | undefined,
) {
  const queryClient = useQueryClient()

  const [rowOffset, setRowOffset] = useState(0)
  const [selectedRowId, setSelectedRowId] = useState<string | null>(null)
  const [rowPanelTab, setRowPanelTab] =
    useState<CallImportRowSidePanelTabId>('production')
  const [copiedRowId, setCopiedRowId] = useState<string | null>(null)
  const [copiedTranscriptField, setCopiedTranscriptField] = useState<{
    rowId: string
    field: 'production' | 'diarised'
  } | null>(null)

  const handleCopyConversationId = (
    row: CallImportRow,
    event: React.MouseEvent,
  ) => {
    event.preventDefault()
    event.stopPropagation()
    const text = row.conversation_id || ''
    if (!text) return
    copyTextToClipboard(text, () => {
      setCopiedRowId(row.id)
      window.setTimeout(() => {
        setCopiedRowId((current) => (current === row.id ? null : current))
      }, 1500)
    })
  }

  const handleCopyTranscript = (
    row: CallImportRow,
    field: 'production' | 'diarised',
    event: React.MouseEvent,
  ) => {
    event.preventDefault()
    event.stopPropagation()
    const text =
      field === 'production'
        ? row.transcript || ''
        : row.diarised_transcript || ''
    if (!text) return
    copyTextToClipboard(text, () => {
      setCopiedTranscriptField({ rowId: row.id, field })
      window.setTimeout(() => {
        setCopiedTranscriptField((current) =>
          current?.rowId === row.id && current?.field === field ? null : current,
        )
      }, 1500)
    })
  }

  const [rowSearchInput, setRowSearchInput] = useState('')
  const [rowSearchQuery, setRowSearchQuery] = useState('')
  const [diarisedStatusFilter, setDiarisedStatusFilter] =
    useState<DiarisedStatusFilter>('all')
  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(new Set())
  const [bulkSelectionFilter, setBulkSelectionFilter] = useState<{
    q?: string
    diarised_status?: string
  } | null>(null)
  const [selectAllError, setSelectAllError] = useState<string | null>(null)

  useEffect(() => {
    const handle = setTimeout(() => {
      setRowSearchQuery(rowSearchInput.trim())
    }, 250)
    return () => clearTimeout(handle)
  }, [rowSearchInput])

  useEffect(() => {
    setRowOffset(0)
  }, [rowSearchQuery, diarisedStatusFilter])

  useEffect(() => {
    setSelectedRowIds(new Set())
    setSelectAllError(null)
  }, [rowSearchQuery, diarisedStatusFilter])

  const queryParams = useMemo(
    () => ({
      row_limit: ROW_PAGE_SIZE,
      row_offset: rowOffset,
      q: rowSearchQuery || undefined,
      diarised_status:
        diarisedStatusFilter === 'all' ? undefined : diarisedStatusFilter,
    }),
    [rowOffset, rowSearchQuery, diarisedStatusFilter],
  )

  const {
    data: rowsPage,
    isLoading: rowsLoading,
    isFetching: rowsFetching,
    refetch: refetchRows,
  } = useQuery({
    queryKey: ['call-import', activeWorkspaceId, id, 'rows', queryParams],
    queryFn: () => apiClient.callImports.getCallImport(id, queryParams),
    enabled: !!id,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
    refetchInterval: () => importRowsPollMs(headerData),
  })

  const importRowsLive = importRowsPollMs(headerData) !== false
  const importRowsWereLive = useRef(false)
  useEffect(() => {
    if (importRowsLive) {
      importRowsWereLive.current = true
      return
    }
    if (!importRowsWereLive.current || !id) return
    importRowsWereLive.current = false
    void queryClient.invalidateQueries({
      queryKey: ['call-import', activeWorkspaceId, id, 'rows'],
    })
    void queryClient.invalidateQueries({
      queryKey: ['call-import', activeWorkspaceId, id, 'row'],
    })
  }, [importRowsLive, id, activeWorkspaceId, queryClient])

  const totalRows = headerData?.total_rows ?? 0
  const hasActiveFilter =
    !!rowSearchQuery || diarisedStatusFilter !== 'all'
  const listRowFilter = (): { q?: string; diarised_status?: string } => ({
    ...(rowSearchQuery.trim() ? { q: rowSearchQuery.trim() } : {}),
    ...(diarisedStatusFilter !== 'all'
      ? { diarised_status: diarisedStatusFilter }
      : {}),
  })
  const filteredTotalRows = hasActiveFilter
    ? rowsPage?.filtered_total_rows ?? 0
    : totalRows
  const rowPage = Math.floor(rowOffset / ROW_PAGE_SIZE) + 1
  const rowTotalPages = Math.max(1, Math.ceil(filteredTotalRows / ROW_PAGE_SIZE))

  const rows = rowsPage?.rows ?? []
  const selectedListRow = rows.find((r) => r.id === selectedRowId) ?? null

  const { data: selectedRowDetail } = useQuery({
    queryKey: ['call-import', activeWorkspaceId, id, 'row', selectedRowId],
    queryFn: () => apiClient.callImports.getCallImportRow(id, selectedRowId!),
    enabled: !!id && !!selectedRowId,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchInterval: () => importRowsPollMs(headerData),
  })

  const selectedRow = selectedRowDetail ?? selectedListRow

  useEffect(() => {
    if (!selectedRowId || !headerData) return
    const visibleRows = rowsPage?.rows ?? []
    if (!visibleRows.some((r) => r.id === selectedRowId)) {
      setSelectedRowId(null)
    }
  }, [rowsPage, selectedRowId, headerData])

  useEffect(() => {
    if (!id || !rowsPage) return
    const nextOffset = rowOffset + ROW_PAGE_SIZE
    if (nextOffset >= filteredTotalRows) return
    const nextParams = { ...queryParams, row_offset: nextOffset }
    void queryClient.prefetchQuery({
      queryKey: ['call-import', activeWorkspaceId, id, 'rows', nextParams],
      queryFn: () => apiClient.callImports.getCallImport(id, nextParams),
      staleTime: 60_000,
    })
  }, [
    id,
    rowOffset,
    filteredTotalRows,
    queryParams,
    activeWorkspaceId,
    queryClient,
    rowsPage,
  ])

  const selectedOnPage = rows.filter((r) => selectedRowIds.has(r.id))
  const selectedOnPageCount = selectedOnPage.length
  const selectedCount = bulkSelectionFilter
    ? filteredTotalRows
    : selectedRowIds.size
  const allOnPageSelected =
    rows.length > 0 && selectedOnPageCount === rows.length
  const allMatchingSelected =
    bulkSelectionFilter !== null ||
    (filteredTotalRows > 0 && selectedRowIds.size >= filteredTotalRows)
  const transcribeReadySelection = selectedOnPage.filter(
    (r) =>
      !!r.recording_s3_key &&
      r.diarised_transcript_status !== 'pending' &&
      r.diarised_transcript_status !== 'running',
  )
  const cancellableSelection = selectedOnPage.filter(
    (r) =>
      r.diarised_transcript_status === 'pending' ||
      r.diarised_transcript_status === 'running',
  )
  const selectionSpansPages =
    bulkSelectionFilter !== null || selectedRowIds.size > selectedOnPageCount

  return {
    rowOffset,
    setRowOffset,
    selectedRowId,
    setSelectedRowId,
    rowPanelTab,
    setRowPanelTab,
    copiedRowId,
    copiedTranscriptField,
    handleCopyConversationId,
    handleCopyTranscript,
    rowSearchInput,
    setRowSearchInput,
    rowSearchQuery,
    diarisedStatusFilter,
    setDiarisedStatusFilter,
    selectedRowIds,
    setSelectedRowIds,
    bulkSelectionFilter,
    setBulkSelectionFilter,
    selectAllError,
    setSelectAllError,
    rowsPage,
    rowsLoading,
    rowsFetching,
    refetchRows,
    rows,
    selectedRow,
    selectedRowDetail,
    filteredTotalRows,
    hasActiveFilter,
    rowPage,
    rowTotalPages,
    listRowFilter,
    selectedCount,
    selectedOnPageCount,
    allOnPageSelected,
    allMatchingSelected,
    transcribeReadySelection,
    cancellableSelection,
    selectionSpansPages,
  }
}
