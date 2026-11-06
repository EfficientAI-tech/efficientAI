import type { Dispatch, SetStateAction } from 'react'
import type { UseMutationResult } from '@tanstack/react-query'
import type { ProviderModelValue } from '../../../../components/providers/ProviderModelPicker'
import type { AIProvider, CallImport, CallImportEvaluation } from '../../../../types/api'
import type { apiClient } from '../../../../lib/api'
import type { CallImportMetricRow } from '../../callImportMetricList'

export type ImportRunEvaluationModalProps = {
  open: boolean
  setShowRunEval: (open: boolean) => void
  data: CallImport
  metrics: CallImportMetricRow[]
  selectedMetricIds: string[]
  setSelectedMetricIds: Dispatch<SetStateAction<string[]>>
  toggleMetric: (metricId: string) => void
  toggleParentMetric: (parent: unknown) => void
  runDraftName: string
  setRunDraftName: (value: string) => void
  runEvaluationMutation: UseMutationResult<
    CallImportEvaluation,
    Error,
    Parameters<typeof apiClient.callImports.createCallImportEvaluation>[1],
    unknown
  >
  evalTelephonyProvider: string
  setEvalTelephonyProvider: (value: string) => void
  evalTelephonyIntegrationId: string
  setEvalTelephonyIntegrationId: (value: string) => void
  classificationLLM: ProviderModelValue
  setClassificationLLM: (value: ProviderModelValue) => void
  runLLM: ProviderModelValue
  setRunLLM: Dispatch<SetStateAction<ProviderModelValue>>
  metricLLMOverrides: Record<string, ProviderModelValue>
  setMetricLLMOverrides: Dispatch<SetStateAction<Record<string, ProviderModelValue>>>
  showAdvancedLLM: boolean
  setShowAdvancedLLM: Dispatch<SetStateAction<boolean>>
  transcribeOverwrite: boolean
  setTranscribeOverwrite: (value: boolean) => void
  evalTranscribeMode: 'stt_llm' | 'llm_only'
  setEvalTranscribeMode: (mode: 'stt_llm' | 'llm_only') => void
  evalTranscriptSource: 'production' | 'diarised'
  setEvalTranscriptSource: (source: 'production' | 'diarised') => void
  evalSTT: ProviderModelValue
  setEvalSTT: (value: ProviderModelValue) => void
  evalSTTLanguage: string
  setEvalSTTLanguage: (value: string) => void
  evalDiariserLLM: ProviderModelValue
  setEvalDiariserLLM: (value: ProviderModelValue) => void
  evalDiarisationPrompt: string
  setEvalDiarisationPrompt: (value: string) => void
  isManualAudioImport: boolean
  aiProviders: AIProvider[]
  defaultDiarisationPrompt: string | undefined
  setPartialsImportError: (message: string | null) => void
  setSelectedPartialId: (id: string) => void
  setPartialsSearchInput: (value: string) => void
  setPartialsSearchQuery: (query: string) => void
  setPartialsImportTarget: (target: 'standalone' | 'eval' | null) => void
  openSavePartialModal: (target: 'standalone' | 'eval') => void
}
