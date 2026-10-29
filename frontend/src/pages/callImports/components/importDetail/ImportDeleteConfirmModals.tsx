import ConfirmModal from '../../../../components/ConfirmModal'
import type { CallImport, CallImportRow } from '../../../../types/api'
import type { UseMutationResult } from '@tanstack/react-query'

export type ImportDeleteConfirmModalsProps = {
  importId: string
  data: CallImport
  showDeleteImport: boolean
  setShowDeleteImport: (open: boolean) => void
  deleteError: string | null
  setDeleteError: (message: string | null) => void
  deleteImportMutation: UseMutationResult<unknown, unknown, string, unknown>
  showBulkDeleteEvals: boolean
  setShowBulkDeleteEvals: (open: boolean) => void
  selectedEvalIds: Set<string>
  bulkDeleteEvalsError: string | null
  setBulkDeleteEvalsError: (message: string | null) => void
  bulkDeleteEvalsMutation: UseMutationResult<unknown, unknown, string[], unknown>
  pendingDeleteRow: CallImportRow | null
  setPendingDeleteRow: (row: CallImportRow | null) => void
  deleteRowMutation: UseMutationResult<
    unknown,
    unknown,
    { importId: string; rowId: string },
    unknown
  >
  showBulkDeleteRows: boolean
  setShowBulkDeleteRows: (open: boolean) => void
  selectedRowIds: Set<string>
  bulkDeleteRowsError: string | null
  setBulkDeleteRowsError: (message: string | null) => void
  bulkSelectionFilter: { q?: string; diarised_status?: string } | null
  bulkDeleteRowsMutation: UseMutationResult<
    unknown,
    unknown,
    { rowIds?: string[]; rowFilter?: { q?: string; diarised_status?: string } },
    unknown
  >
}

export function ImportDeleteConfirmModals(props: ImportDeleteConfirmModalsProps) {
  const {
    importId,
    data,
    showDeleteImport,
    setShowDeleteImport,
    deleteError,
    setDeleteError,
    deleteImportMutation,
    showBulkDeleteEvals,
    setShowBulkDeleteEvals,
    selectedEvalIds,
    bulkDeleteEvalsError,
    setBulkDeleteEvalsError,
    bulkDeleteEvalsMutation,
    pendingDeleteRow,
    setPendingDeleteRow,
    deleteRowMutation,
    showBulkDeleteRows,
    setShowBulkDeleteRows,
    selectedRowIds,
    bulkDeleteRowsError,
    setBulkDeleteRowsError,
    bulkSelectionFilter,
    bulkDeleteRowsMutation,
  } = props

  return (
    <>

      <ConfirmModal
        isOpen={showDeleteImport}
        title="Delete call import?"
        description={(() => {
          const name = data.original_filename || '(unnamed)'
          const inFlight =
            data.status === 'pending' ||
            data.status === 'processing' ||
            data.status === 'deleting'
          const lines = [
            `“${name}” will be permanently deleted, along with all of its recordings.`,
            inFlight
              ? 'This batch is still processing — pending tasks will be revoked before deletion.'
              : '',
            'This cannot be undone.',
            deleteError ? `Error: ${deleteError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        confirmPhrase="confirm"
        variant="danger"
        isLoading={deleteImportMutation.isPending}
        onConfirm={() => deleteImportMutation.mutate(data.id)}
        onCancel={() => {
          if (deleteImportMutation.isPending) return
          setShowDeleteImport(false)
          setDeleteError(null)
        }}
      />

      <ConfirmModal
        isOpen={showBulkDeleteEvals}
        title={
          selectedEvalIds.size === 1
            ? 'Delete this evaluation run?'
            : `Delete ${selectedEvalIds.size} evaluation runs?`
        }
        description={(() => {
          const lines = [
            selectedEvalIds.size === 1
              ? 'This run and all of its per-row score records will be permanently removed.'
              : `These ${selectedEvalIds.size} runs and all of their per-row score records will be permanently removed.`,
            'In-flight runs will have their pending tasks revoked before deletion.',
            'The underlying CSV import stays intact, so you can re-run later.',
            'This cannot be undone.',
            bulkDeleteEvalsError ? `Error: ${bulkDeleteEvalsError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={bulkDeleteEvalsMutation.isPending}
        onConfirm={() => {
          bulkDeleteEvalsMutation.mutate(Array.from(selectedEvalIds))
        }}
        onCancel={() => {
          if (bulkDeleteEvalsMutation.isPending) return
          setShowBulkDeleteEvals(false)
          setBulkDeleteEvalsError(null)
        }}
      />

      <ConfirmModal
        isOpen={pendingDeleteRow !== null}
        title="Delete this recording?"
        description={(() => {
          if (!pendingDeleteRow) return ''
          const callId = pendingDeleteRow.conversation_id
          const hasRecording = !!pendingDeleteRow.recording_s3_key
          const lines = [
            `The row for CallID ${callId} will be permanently deleted.`,
            hasRecording
              ? 'The associated recording will also be permanently deleted.'
              : 'No recording is stored for this row yet, so only the row record will be removed.',
            'This cannot be undone.',
            deleteError ? `Error: ${deleteError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={deleteRowMutation.isPending}
        onConfirm={() => {
          if (pendingDeleteRow && importId) {
            deleteRowMutation.mutate({
              importId,
              rowId: pendingDeleteRow.id,
            })
          }
        }}
        onCancel={() => {
          if (deleteRowMutation.isPending) return
          setPendingDeleteRow(null)
          setDeleteError(null)
        }}
      />

      <ConfirmModal
        isOpen={showBulkDeleteRows}
        title={
          selectedRowIds.size === 1
            ? 'Delete this row?'
            : `Delete ${selectedRowIds.size} rows?`
        }
        description={(() => {
          const lines = [
            selectedRowIds.size === 1
              ? 'The selected row will be permanently deleted, along with its recording.'
              : `${selectedRowIds.size} rows will be permanently deleted, along with their recordings.`,
            'In-flight transcribe / download tasks for these rows will be revoked.',
            'This cannot be undone.',
            bulkDeleteRowsError ? `Error: ${bulkDeleteRowsError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={bulkDeleteRowsMutation.isPending}
        onConfirm={() => {
          if (bulkSelectionFilter) {
            bulkDeleteRowsMutation.mutate({ rowFilter: bulkSelectionFilter })
            return
          }
          if (selectedRowIds.size === 0) return
          bulkDeleteRowsMutation.mutate({ rowIds: Array.from(selectedRowIds) })
        }}
        onCancel={() => {
          if (bulkDeleteRowsMutation.isPending) return
          setShowBulkDeleteRows(false)
          setBulkDeleteRowsError(null)
        }}
      />
    </>
  )
}
