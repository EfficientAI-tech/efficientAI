import type { UseMutationResult } from '@tanstack/react-query'
import type { ProviderModelValue } from '../../../../components/providers/ProviderModelPicker'
import type { AIProvider, CallImportRow } from '../../../../types/api'

export type ImportTranscribeModalsProps = {
  partialsImportTarget: 'standalone' | 'eval' | null
  closePartialsImportModal: () => void
  importPartialMutation: UseMutationResult<unknown, unknown, string, unknown>
  partialsSearchInput: string
  setPartialsSearchInput: (value: string) => void
  isLoadingPartials: boolean
  promptPartials: Array<{ id: string; name: string; description?: string | null }>
  partialsSearchQuery: string
  selectedPartialId: string
  setSelectedPartialId: (id: string) => void
  partialsImportError: string | null
  savePartialTarget: 'standalone' | 'eval' | null
  closeSavePartialModal: () => void
  savePartialMutation: UseMutationResult<
    unknown,
    unknown,
    {
      content: string
      mode: 'new' | 'existing'
      name?: string
      description?: string
      partialId?: string
      changeSummary?: string
    },
    unknown
  >
  savePartialMode: 'new' | 'existing'
  setSavePartialMode: (mode: 'new' | 'existing') => void
  setSavePartialError: (message: string | null) => void
  transcribeDiarisationPrompt: string
  evalDiarisationPrompt: string
  savePartialName: string
  setSavePartialName: (value: string) => void
  savePartialDescription: string
  setSavePartialDescription: (value: string) => void
  savePartialExistingId: string
  setSavePartialExistingId: (id: string) => void
  savePartialChangeSummary: string
  setSavePartialChangeSummary: (value: string) => void
  savePartialError: string | null
  savePartialSuccess: string | null
  showTranscribeModal: boolean
  transcribeTargetRows: CallImportRow[] | null
  bulkSelectionFilter: { q?: string; diarised_status?: string } | null
  selectedCount: number
  transcribeMode: 'stt_llm' | 'llm_only'
  setTranscribeMode: (mode: 'stt_llm' | 'llm_only') => void
  transcribeSTT: ProviderModelValue
  setTranscribeSTT: (value: ProviderModelValue) => void
  transcribeLanguage: string
  setTranscribeLanguage: (value: string) => void
  transcribeDiariserLLM: ProviderModelValue
  setTranscribeDiariserLLM: (value: ProviderModelValue) => void
  aiProviders: AIProvider[]
  defaultDiarisationPrompt: string | undefined
  openSavePartialModal: (target: 'standalone' | 'eval') => void
  setPartialsImportError: (message: string | null) => void
  setPartialsSearchQuery: (query: string) => void
  setPartialsImportTarget: (target: 'standalone' | 'eval' | null) => void
  setTranscribeDiarisationPrompt: (value: string) => void
  transcribeOverwriteStandalone: boolean
  setTranscribeOverwriteStandalone: (value: boolean) => void
  transcribeError: string | null
  transcribeRowsMutation: UseMutationResult<
    unknown,
    unknown,
    {
      rowIds: string[] | null
      mode: 'stt_llm' | 'llm_only'
      stt: ProviderModelValue
      diariserLLM: ProviderModelValue
      diarisationPrompt: string
      language: string
      overwrite: boolean
    },
    unknown
  >
  setShowTranscribeModal: (open: boolean) => void
  setTranscribeTargetRows: (rows: CallImportRow[] | null) => void
  showBulkActionsModal: boolean
  setShowBulkActionsModal: (open: boolean) => void
  bulkActionError: string | null
  setBulkActionError: (message: string | null) => void
  bulkActionResult: string | null
  setBulkActionResult: (message: string | null) => void
  selectionSpansPages: boolean
  transcribeReadySelection: CallImportRow[]
  openTranscribeModal: (rows: CallImportRow[]) => void
  selectedRowIds: Set<string>
  bulkCancelDiarisationMutation: UseMutationResult<
    unknown,
    unknown,
    { rowIds?: string[]; rowFilter?: { q?: string; diarised_status?: string } },
    unknown
  >
  cancellableSelection: CallImportRow[]
  setBulkDeleteRowsError: (message: string | null) => void
  setShowBulkDeleteRows: (open: boolean) => void
}
