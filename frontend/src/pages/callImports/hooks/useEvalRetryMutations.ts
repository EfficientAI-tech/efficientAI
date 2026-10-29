import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import {
  isLLMSelectionComplete,
  resolveLLMModelForSubmit,
  isClassificationCapableModel,
  mergeClassificationOverrides,
  seedClassificationLLM,
} from '../../../lib/llmModelOptions'
import type {
  AIProvider,
  CallImportEvaluation,
  CallImportEvaluationRetryResponse,
} from '../../../types/api'
import type { ProviderModelValue } from '../../../components/providers/ProviderModelPicker'
import {
  credentialSelectionFromState,
  initialTelephonySelection,
} from '../components/TelephonyCredentialPicker'
import { formatApiErrorDetail } from '../metricScoresMeta'
import type { BulkEvaluationOperation } from '../evaluationBulkOperation'

export const STT_PROVIDER_ALLOWLIST = [
  'deepgram',
  'openai',
  'elevenlabs',
  'sarvam',
  'smallest',
  'google',
]

type CallImportLike = {
  provider?: string | null
  telephony_integration_id?: string | null
} | undefined

export type UseEvalRetryMutationsArgs = {
  callImportId: string | undefined
  evaluationId: string | undefined
  activeWorkspaceId: string | null | undefined
  evaluation: CallImportEvaluation | undefined
  callImport: CallImportLike
  searchQuery: string
  aiProviders: AIProvider[]
  classificationMetricIdSet: Set<string>
  setEvaluationBulkOperationOptimistic: (op: BulkEvaluationOperation | null) => void
  invalidateEvaluationQueries: () => void
  bulkOperationConflictMessage: string
}

export function useEvalRetryMutations({
  callImportId,
  evaluationId,
  activeWorkspaceId,
  evaluation,
  callImport,
  searchQuery,
  aiProviders,
  classificationMetricIdSet,
  setEvaluationBulkOperationOptimistic,
  invalidateEvaluationQueries,
  bulkOperationConflictMessage,
}: UseEvalRetryMutationsArgs) {
  const queryClient = useQueryClient()
  const id = callImportId
  const evalId = evaluationId
  const [retryError, setRetryError] = useState<string | null>(null)
  const [pendingRetryRowId, setPendingRetryRowId] = useState<string | null>(
    null,
  )
  const [retryConfirmOpen, setRetryConfirmOpen] = useState(false)
  // Optional overrides the user can set inside the bulk-retry modal.
  // ``null`` provider/model means "keep the run's saved value" — the
  // mutation only sends each field when the picker holds something
  // different from what's already on the evaluation, so the backend
  // never sees a half-configured payload.
  const [retryLLM, setRetryLLM] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  const [retrySTT, setRetrySTT] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  const [retryTranscribeMode, setRetryTranscribeMode] = useState<
    'stt_llm' | 'llm_only'
  >('llm_only')
  const [retryDiariserLLM, setRetryDiariserLLM] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  const [retryDiarisationPrompt, setRetryDiarisationPrompt] = useState('')
  const [retryTranscribeOverwrite, setRetryTranscribeOverwrite] =
    useState(false)
  const [retryTelephonyProvider, setRetryTelephonyProvider] = useState('')
  const [retryTelephonyIntegrationId, setRetryTelephonyIntegrationId] =
    useState('')

  // "Re-run metrics" UX (separate from the failed-row retry above).
  // The user picks one or more of the run's already-scored metrics
  // and the worker recomputes only those, merging the new scores
  // into the row's existing ``metric_scores`` so other metrics'
  // values stay byte-identical. Backed by the same retry endpoint
  // with ``metric_ids`` + ``include_completed=true``.
  const [rerunMetricsOpen, setRerunMetricsOpen] = useState(false)
  const [rerunMetricIds, setRerunMetricIds] = useState<Set<string>>(
    new Set(),
  )
  const [rerunLLM, setRerunLLM] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  // System 1 (Jev) model for classification metrics in the Retry / Re-run
  // modals. Classification metrics cannot be scored by standard LLM judges,
  // so they get their own picker and are routed via per-metric overrides.
  const [retryClassificationLLM, setRetryClassificationLLM] =
    useState<ProviderModelValue>({ provider: null, model: null, credential_id: null })
  const [rerunClassificationLLM, setRerunClassificationLLM] =
    useState<ProviderModelValue>({ provider: null, model: null, credential_id: null })
  const [rerunError, setRerunError] = useState<string | null>(null)

  const runMetricIds: string[] = evaluation?.selected_metric_ids ?? []
  const retryClassificationIds = runMetricIds.filter((mid) =>
    classificationMetricIdSet.has(mid),
  )
  const rerunSelectedIds = Array.from(rerunMetricIds)
  const rerunClassificationIds = rerunSelectedIds.filter((mid) =>
    classificationMetricIdSet.has(mid),
  )
  const isClassificationSelectionReady = (value: ProviderModelValue) =>
    aiProviders.length > 0 &&
    isLLMSelectionComplete(value, aiProviders) &&
    isClassificationCapableModel(
      resolveLLMModelForSubmit(value, aiProviders) ?? value.model ?? '',
    )
  const classificationOverrideSelection = (value: ProviderModelValue) => ({
    provider: value.provider,
    model: resolveLLMModelForSubmit(value, aiProviders) ?? value.model,
    credential_id: value.credential_id ?? null,
    llm_config: value.llm_config ?? null,
  })

  // Re-enqueue every failed row in this run. The backend filters to
  // ``status='failed'`` server-side, so we don't need to know which
  // rows are currently failing — the button just hands the whole run
  // back to the workers. When the user changed the LLM / STT pickers
  // inside the retry modal we forward those as overrides; the backend
  // persists them onto the run so the next retry defaults to them.
  const retryAllFailedMutation = useMutation({
    mutationFn: () => {
      // Forward LLM overrides only when the picker resolves to a
      // complete selection (catalog model, gateway credential, etc.).
      const llmChanged =
        retryLLM.provider !== (evaluation?.llm_provider ?? null) ||
        retryLLM.model !== (evaluation?.llm_model ?? null) ||
        (retryLLM.credential_id ?? null) !==
          (evaluation?.llm_credential_id ?? null) ||
        JSON.stringify(retryLLM.llm_config ?? null) !==
          JSON.stringify(evaluation?.llm_config ?? null)
      const llmComplete = isLLMSelectionComplete(retryLLM, aiProviders)
      const sttChanged =
        retrySTT.provider !== (evaluation?.stt_provider ?? null) ||
        retrySTT.model !== (evaluation?.stt_model ?? null) ||
        (retrySTT.credential_id ?? null) !==
          (evaluation?.stt_credential_id ?? null)
      const diariserChanged =
        retryDiariserLLM.provider !==
          (evaluation?.diarisation_llm_provider ?? null) ||
        retryDiariserLLM.model !==
          (evaluation?.diarisation_llm_model ?? null) ||
        (retryDiariserLLM.credential_id ?? null) !==
          (evaluation?.diarisation_llm_credential_id ?? null)
      const diariserComplete = isLLMSelectionComplete(
        retryDiariserLLM,
        aiProviders,
      )
      const transcribeModeChanged =
        retryTranscribeMode !== (evaluation?.transcribe_mode ?? 'stt_llm')
      const diarisationPromptChanged =
        retryDiarisationPrompt.trim() !==
        (evaluation?.diarisation_prompt ?? '').trim()
      const telephonySelection = credentialSelectionFromState(
        retryTelephonyProvider,
        retryTelephonyIntegrationId,
      )
      const telephonyChanged =
        (telephonySelection.provider ?? null) !==
          (callImport?.provider ?? null) ||
        (telephonySelection.telephonyIntegrationId ?? null) !==
          (callImport?.telephony_integration_id ?? null)

      // Classification metrics are routed to the System 1 model through
      // per-metric overrides; standard metrics keep the run-level LLM.
      const retryClassificationOverrides =
        retryClassificationIds.length > 0 &&
        isClassificationSelectionReady(retryClassificationLLM)
          ? mergeClassificationOverrides(
              evaluation?.metric_llm_overrides,
              retryClassificationIds,
              runMetricIds,
              classificationOverrideSelection(retryClassificationLLM),
            )
          : undefined
      return apiClient.callImports.retryCallImportEvaluation(id!, evalId!, {
        rowFilter: {
          q: searchQuery.trim() || undefined,
          status: 'failed',
        },
        llmProvider:
          llmChanged && llmComplete ? retryLLM.provider ?? undefined : undefined,
        llmModel:
          llmChanged && llmComplete
            ? resolveLLMModelForSubmit(retryLLM, aiProviders) ??
              retryLLM.model ??
              undefined
            : undefined,
        llmCredentialId:
          llmChanged && llmComplete ? retryLLM.credential_id ?? null : undefined,
        llmConfig: llmChanged ? retryLLM.llm_config ?? null : undefined,
        metricLlmOverrides: retryClassificationOverrides,
        sttProvider:
          sttChanged && retrySTT.provider && retrySTT.model
            ? retrySTT.provider
            : undefined,
        sttModel:
          sttChanged && retrySTT.provider && retrySTT.model
            ? retrySTT.model
            : undefined,
        sttCredentialId:
          sttChanged && retrySTT.provider && retrySTT.model
            ? retrySTT.credential_id ?? null
            : undefined,
        transcribeMode: transcribeModeChanged
          ? retryTranscribeMode
          : undefined,
        diarizationLlmProvider:
          diariserChanged && diariserComplete
            ? retryDiariserLLM.provider ?? undefined
            : undefined,
        diarizationLlmModel:
          diariserChanged && diariserComplete
            ? resolveLLMModelForSubmit(retryDiariserLLM, aiProviders) ??
              retryDiariserLLM.model ??
              undefined
            : undefined,
        diarizationLlmCredentialId:
          diariserChanged && diariserComplete
            ? retryDiariserLLM.credential_id ?? null
            : undefined,
        diarizationPrompt: diarisationPromptChanged
          ? retryDiarisationPrompt.trim() || null
          : undefined,
        transcribeOverwrite: retryTranscribeOverwrite,
        provider: telephonyChanged ? telephonySelection.provider : undefined,
        telephonyIntegrationId: telephonyChanged
          ? telephonySelection.telephonyIntegrationId
          : undefined,
      })
    },
    onMutate: () => {
      setRetryError(null)
      setEvaluationBulkOperationOptimistic('retry')
      invalidateEvaluationQueries()
    },
    onSuccess: (data: CallImportEvaluationRetryResponse) => {
      if (data.requeued > 0) {
        setEvaluationBulkOperationOptimistic('retry')
      } else {
        setEvaluationBulkOperationOptimistic(null)
      }
      invalidateEvaluationQueries()
      queryClient.invalidateQueries({
        queryKey: ['call-import', activeWorkspaceId, id],
      })
      setRetryError(null)
      setRetryConfirmOpen(false)
    },
    onError: (err: any) => {
      setEvaluationBulkOperationOptimistic(null)
      setRetryError(
        err?.response?.status === 409
          ? err?.response?.data?.detail || bulkOperationConflictMessage
          : err?.response?.data?.detail ||
              err?.message ||
              'Failed to retry the evaluation.',
      )
    },
  })

  // Seed the retry pickers from the run's saved config the moment the
  // modal opens, then stop reacting to refetches. The 3s polling on
  // the evaluation query would otherwise clobber whatever the user
  // typed into the pickers, so we deliberately only depend on
  // ``retryConfirmOpen`` here.
  useEffect(() => {
    if (!retryConfirmOpen) return
    if (!evaluation) return
    setRetryLLM({
      provider: evaluation.llm_provider ?? null,
      model: evaluation.llm_model ?? null,
      credential_id: evaluation.llm_credential_id ?? null,
    })
    setRetrySTT({
      provider: evaluation.stt_provider ?? null,
      model: evaluation.stt_model ?? null,
      credential_id: evaluation.stt_credential_id ?? null,
    })
    setRetryTranscribeMode(evaluation.transcribe_mode ?? 'stt_llm')
    setRetryDiariserLLM({
      provider: evaluation.diarisation_llm_provider ?? null,
      model: evaluation.diarisation_llm_model ?? null,
      credential_id: evaluation.diarisation_llm_credential_id ?? null,
    })
    setRetryDiarisationPrompt(evaluation.diarisation_prompt ?? '')
    setRetryTranscribeOverwrite(false)
    const telephonyInitial = initialTelephonySelection(callImport)
    setRetryTelephonyProvider(telephonyInitial.provider)
    setRetryTelephonyIntegrationId(telephonyInitial.integrationId)
    setRetryClassificationLLM(
      seedClassificationLLM(
        (evaluation.selected_metric_ids ?? []).filter((mid) =>
          classificationMetricIdSet.has(mid),
        ),
        evaluation.metric_llm_overrides,
        {
          provider: evaluation.llm_provider ?? null,
          model: evaluation.llm_model ?? null,
          credential_id: evaluation.llm_credential_id ?? null,
          llm_config: evaluation.llm_config ?? null,
        },
      ),
    )
    setRetryError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [retryConfirmOpen])

  // Same seeding pattern for the "Re-run metrics" modal. We default
  // the LLM picker to the run's saved value (no override) and start
  // with no metrics selected — the user must explicitly pick at
  // least one, otherwise the action is a no-op and we surface a
  // disabled state on the submit button.
  useEffect(() => {
    if (!rerunMetricsOpen) return
    if (!evaluation) return
    setRerunLLM({
      provider: evaluation.llm_provider ?? null,
      model: evaluation.llm_model ?? null,
      credential_id: evaluation.llm_credential_id ?? null,
      llm_config: evaluation.llm_config ?? null,
    })
    setRerunMetricIds(new Set())
    setRerunError(null)
    setRerunClassificationLLM(
      seedClassificationLLM(
        (evaluation.selected_metric_ids ?? []).filter((mid) =>
          classificationMetricIdSet.has(mid),
        ),
        evaluation.metric_llm_overrides,
        {
          provider: evaluation.llm_provider ?? null,
          model: evaluation.llm_model ?? null,
          credential_id: evaluation.llm_credential_id ?? null,
          llm_config: evaluation.llm_config ?? null,
        },
      ),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rerunMetricsOpen])

  // Metric-subset re-run mutation. Forwards ``metric_ids`` to the
  // backend so the worker recomputes only those metrics, with
  // ``include_completed`` flipped on so already-successful rows are
  // eligible (the whole point of this UI). LLM overrides flow
  // through the same retry payload — when the user changes the LLM
  // picker, the backend persists the new model on the run and uses
  // it for every selected metric.
  const rerunMetricsMutation = useMutation({
    mutationFn: () => {
      const metricIds = Array.from(rerunMetricIds)
      if (!metricIds.length) {
        return Promise.reject(
          new Error('Pick at least one metric to re-run.'),
        )
      }
      const llmChanged =
        rerunLLM.provider !== (evaluation?.llm_provider ?? null) ||
        rerunLLM.model !== (evaluation?.llm_model ?? null) ||
        (rerunLLM.credential_id ?? null) !==
          (evaluation?.llm_credential_id ?? null) ||
        JSON.stringify(rerunLLM.llm_config ?? null) !==
          JSON.stringify(evaluation?.llm_config ?? null)
      const llmComplete = isLLMSelectionComplete(rerunLLM, aiProviders)
      const rerunClassificationOverrides =
        rerunClassificationIds.length > 0 &&
        isClassificationSelectionReady(rerunClassificationLLM)
          ? mergeClassificationOverrides(
              evaluation?.metric_llm_overrides,
              rerunClassificationIds,
              runMetricIds,
              classificationOverrideSelection(rerunClassificationLLM),
            )
          : undefined
      return apiClient.callImports.retryCallImportEvaluation(id!, evalId!, {
        metricIds,
        includeCompleted: true,
        llmProvider:
          llmChanged && llmComplete ? rerunLLM.provider ?? undefined : undefined,
        llmModel:
          llmChanged && llmComplete
            ? resolveLLMModelForSubmit(rerunLLM, aiProviders) ??
              rerunLLM.model ??
              undefined
            : undefined,
        llmCredentialId:
          llmChanged && llmComplete ? rerunLLM.credential_id ?? null : undefined,
        llmConfig: llmChanged ? rerunLLM.llm_config ?? null : undefined,
        metricLlmOverrides: rerunClassificationOverrides,
      })
    },
    onMutate: () => {
      setRerunError(null)
      setEvaluationBulkOperationOptimistic('retry')
      invalidateEvaluationQueries()
    },
    onSuccess: (data: CallImportEvaluationRetryResponse) => {
      if (data.requeued > 0) {
        setEvaluationBulkOperationOptimistic('retry')
      } else {
        setEvaluationBulkOperationOptimistic(null)
      }
      invalidateEvaluationQueries()
      setRerunError(null)
      setRerunMetricsOpen(false)
    },
    onError: (err: any) => {
      setEvaluationBulkOperationOptimistic(null)
      const fallback = 'Failed to re-run the selected metrics.'
      setRerunError(
        err?.response?.status === 409
          ? formatApiErrorDetail(
              err?.response?.data?.detail,
              bulkOperationConflictMessage,
            )
          : formatApiErrorDetail(err?.response?.data?.detail, fallback) ||
              err?.message ||
              fallback,
      )
    },
  })

  // Re-enqueue a single failed row. Returns the refreshed row so we
  // can prime the cache; the next polling tick (3s while running)
  // will catch any subsequent status flips.
  const retryRowMutation = useMutation({
    mutationFn: (rowId: string) =>
      apiClient.callImports.retryCallImportEvaluationRow(id!, evalId!, rowId),
    onMutate: (rowId) => {
      setPendingRetryRowId(rowId)
      setRetryError(null)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation', activeWorkspaceId, id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-rows', activeWorkspaceId, id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', activeWorkspaceId, id],
      })
    },
    onError: (err: any) => {
      setRetryError(
        err?.response?.status === 409
          ? err?.response?.data?.detail || bulkOperationConflictMessage
          : err?.response?.data?.detail ||
              err?.message ||
              'Failed to retry this row.',
      )
    },
    onSettled: () => {
      setPendingRetryRowId(null)
    },
  })

  return {
    retryError,
    setRetryError,
    pendingRetryRowId,
    retryConfirmOpen,
    setRetryConfirmOpen,
    retryLLM,
    setRetryLLM,
    retrySTT,
    setRetrySTT,
    retryTranscribeMode,
    setRetryTranscribeMode,
    retryDiariserLLM,
    setRetryDiariserLLM,
    retryDiarisationPrompt,
    setRetryDiarisationPrompt,
    retryTranscribeOverwrite,
    setRetryTranscribeOverwrite,
    retryTelephonyProvider,
    setRetryTelephonyProvider,
    retryTelephonyIntegrationId,
    setRetryTelephonyIntegrationId,
    retryClassificationLLM,
    setRetryClassificationLLM,
    rerunMetricsOpen,
    setRerunMetricsOpen,
    rerunMetricIds,
    setRerunMetricIds,
    rerunLLM,
    setRerunLLM,
    rerunClassificationLLM,
    setRerunClassificationLLM,
    rerunError,
    setRerunError,
    retryAllFailedMutation,
    retryRowMutation,
    rerunMetricsMutation,
  }
}
