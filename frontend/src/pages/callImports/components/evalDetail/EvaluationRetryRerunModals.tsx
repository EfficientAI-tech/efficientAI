import { createPortal } from 'react-dom'
import {
  AlertCircle,
  RefreshCw,
  RotateCw,
  X,
} from 'lucide-react'
import Button from '../../../../components/Button'
import ProviderModelPicker from '../../../../components/providers/ProviderModelPicker'
import {
  isLLMSelectionComplete,
  isStandardJudgeModel,
} from '../../../../lib/llmModelOptions'
import type { AIProvider, CallImportEvaluation } from '../../../../types/api'
import RunEvaluationClassificationModel from '../RunEvaluationClassificationModel'
import TelephonyCredentialPicker, {
  isCredentialSelectionValid,
} from '../TelephonyCredentialPicker'
import { STT_PROVIDER_ALLOWLIST, type useEvalRetryMutations } from '../../hooks/useEvalRetryMutations'

type RetryApi = ReturnType<typeof useEvalRetryMutations>

export type EvaluationRetryRerunModalsProps = {
  evaluation: CallImportEvaluation
  displayMetrics: { id: string; name: string }[]
  metricNameById: Map<string, string>
  aiProviders: AIProvider[]
  hasClassificationCredential: boolean
  retry: RetryApi
  retryClassificationIds: string[]
  retryHasStandard: boolean
  rerunClassificationIds: string[]
  rerunHasStandard: boolean
  isClassificationSelectionReady: (value: import('../../../../components/providers/ProviderModelPicker').ProviderModelValue) => boolean
  retryClassificationReady: boolean
  rerunClassificationReady: boolean
}

export function EvaluationRetryRerunModals({
  evaluation,
  displayMetrics,
  metricNameById,
  aiProviders,
  hasClassificationCredential,
  retry,
  retryClassificationIds,
  retryHasStandard,
  rerunClassificationIds,
  rerunHasStandard,
  isClassificationSelectionReady,
  retryClassificationReady,
  rerunClassificationReady,
}: EvaluationRetryRerunModalsProps) {
  const {
    retryError,
    setRetryError,
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
    retryAllFailedMutation,
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
    rerunMetricsMutation,
  } = retry
  return (
    <>
      {retryConfirmOpen &&
        createPortal(
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
              <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">
                    Retry {evaluation.failed_rows} failed row
                    {evaluation.failed_rows === 1 ? '' : 's'}
                  </h2>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Reset failed rows and re-run them. You can keep the
                    run's existing LLM / STT or switch to a different
                    provider+model just for this retry pass — your
                    pick is saved onto the run so future retries
                    default to it.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    if (retryAllFailedMutation.isPending) return
                    setRetryConfirmOpen(false)
                    setRetryError(null)
                  }}
                  disabled={retryAllFailedMutation.isPending}
                  className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
                  aria-label="Close retry modal"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="px-6 py-5 overflow-y-auto flex-1 space-y-5">
                <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700 space-y-1">
                  <div>
                    <span className="font-medium">Currently saved:</span>{' '}
                    LLM ={' '}
                    <span className="font-mono">
                      {evaluation.llm_provider ?? '—'} /{' '}
                      {evaluation.llm_model ?? '—'}
                    </span>
                  </div>
                  <div>
                    STT ={' '}
                    <span className="font-mono">
                      {evaluation.stt_provider ?? '—'} /{' '}
                      {evaluation.stt_model ?? '—'}
                    </span>{' '}
                    · Transcript source ={' '}
                    <span className="font-mono">
                      {evaluation.transcript_source}
                    </span>
                  </div>
                </div>

                <div className="rounded-md border border-gray-200 bg-gray-50 p-4 space-y-3">
                  <div>
                    <h3 className="text-sm font-medium text-gray-900">
                      Recording fetch
                    </h3>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Used when failed rows still need to download audio from
                      Exotel or another provider. Exotel batches require a
                      Recording URL column in the CSV. Switch credentials here if
                      the original batch used the wrong integration.
                    </p>
                  </div>
                  <TelephonyCredentialPicker
                    selectedProvider={retryTelephonyProvider}
                    selectedIntegrationId={retryTelephonyIntegrationId}
                    onProviderChange={setRetryTelephonyProvider}
                    onIntegrationChange={setRetryTelephonyIntegrationId}
                    disabled={retryAllFailedMutation.isPending}
                    compact
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    LLM for re-evaluation
                  </label>
                  <p className="text-xs text-gray-500 mb-2">
                    Used to score every retried row. Leave as-is to
                    re-run with the same LLM as before.
                  </p>
                  {(retryHasStandard || retryClassificationIds.length === 0) && (
                    <ProviderModelPicker
                      kind="llm"
                      value={retryLLM}
                      onChange={setRetryLLM}
                      allowCredentialPick
                      defaultLabel="Pick an LLM provider"
                      modelFilter={isStandardJudgeModel}
                      incompatibleHint="This credential only exposes Jev classification models, which cannot score standard metrics. Use Together Tev or a chat model instead."
                    />
                  )}
                  {retryClassificationIds.length > 0 && (
                    <div className="mt-3">
                      <RunEvaluationClassificationModel
                        value={retryClassificationLLM}
                        onChange={setRetryClassificationLLM}
                        metricNames={retryClassificationIds.map((mid) => metricNameById.get(mid) ?? mid)}
                        hasCompatibleCredential={hasClassificationCredential}
                        complete={isClassificationSelectionReady(retryClassificationLLM)}
                      />
                    </div>
                  )}
                </div>

                {evaluation.transcript_source === 'diarised' && (
                  <div className="rounded-md border border-gray-200 bg-gray-50 p-3 space-y-3">
                    <div>
                      <p className="text-sm font-medium text-gray-900">
                        Auto-diarise missing or overwritten transcripts
                      </p>
                      <p className="text-[11px] text-gray-500 mt-0.5">
                        Rows that already have a diarised transcript are
                        re-scored only unless you opt to overwrite below.
                        Pick the same pipeline you would use for a new run.
                      </p>
                    </div>
                    <div
                      role="tablist"
                      aria-label="Auto-diarise pipeline"
                      className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5"
                    >
                      <button
                        type="button"
                        role="tab"
                        aria-pressed={retryTranscribeMode === 'llm_only'}
                        onClick={() => setRetryTranscribeMode('llm_only')}
                        className={`px-3 py-1 text-[11px] font-medium rounded-md transition ${
                          retryTranscribeMode === 'llm_only'
                            ? 'bg-primary-50 text-primary-700 ring-1 ring-inset ring-primary-200'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        LLM only (audio in)
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-pressed={retryTranscribeMode === 'stt_llm'}
                        onClick={() => setRetryTranscribeMode('stt_llm')}
                        className={`px-3 py-1 text-[11px] font-medium rounded-md transition inline-flex items-center gap-1.5 ${
                          retryTranscribeMode === 'stt_llm'
                            ? 'bg-primary-50 text-primary-700 ring-1 ring-inset ring-primary-200'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        STT + LLM diariser
                        <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-gray-600">
                          Advanced
                        </span>
                      </button>
                    </div>
                    {retryTranscribeMode === 'stt_llm' && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          STT for re-diarisation
                        </label>
                        <ProviderModelPicker
                          kind="stt"
                          value={retrySTT}
                          onChange={setRetrySTT}
                          providerAllowList={STT_PROVIDER_ALLOWLIST}
                          allowCredentialPick
                          defaultLabel="Pick an STT provider"
                        />
                      </div>
                    )}
                    <label className="flex items-start gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={retryTranscribeOverwrite}
                        onChange={(e) =>
                          setRetryTranscribeOverwrite(e.target.checked)
                        }
                        className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span>
                        <span className="font-medium">
                          Re-diarise existing transcripts
                        </span>{' '}
                        <span className="text-gray-500">
                          — wipe the diarised transcript on every retried
                          row so the pipeline runs from scratch. Leave
                          unchecked to keep existing transcripts and only
                          re-score with the new LLM.
                        </span>
                      </span>
                    </label>
                    <div className="pt-3 border-t border-gray-200 space-y-2">
                      <p className="text-xs font-medium text-gray-700">
                        {retryTranscribeMode === 'stt_llm'
                          ? 'Diariser LLM'
                          : 'Multimodal diariser LLM'}
                      </p>
                      <p className="text-[11px] text-gray-500">
                        {retryTranscribeMode === 'stt_llm'
                          ? 'Used after STT when a row needs diarisation or overwrite.'
                          : 'Receives audio directly when a row needs diarisation or overwrite.'}
                      </p>
                      <ProviderModelPicker
                        kind="llm"
                        value={retryDiariserLLM}
                        onChange={setRetryDiariserLLM}
                        allowCredentialPick
                        audioCapableOnly={retryTranscribeMode === 'llm_only'}
                        defaultLabel="Pick a diariser LLM"
                      />
                      <textarea
                        value={retryDiarisationPrompt}
                        onChange={(e) =>
                          setRetryDiarisationPrompt(e.target.value)
                        }
                        rows={3}
                        placeholder="Diarisation prompt (optional override)"
                        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                      />
                    </div>
                  </div>
                )}

                <div className="rounded-md bg-amber-50 border border-amber-200 p-3 text-xs text-amber-900">
                  Completed rows and rows currently in progress are
                  left alone, so this is safe to run mid-evaluation.
                  The picked LLM / STT becomes the run's new default
                  for any future retry from this screen.
                </div>

                {retryError && (
                  <div className="rounded-md bg-red-50 border border-red-200 p-3">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                      <p className="text-sm text-red-800">{retryError}</p>
                    </div>
                  </div>
                )}
              </div>

              <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    if (retryAllFailedMutation.isPending) return
                    setRetryConfirmOpen(false)
                    setRetryError(null)
                  }}
                  disabled={retryAllFailedMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  leftIcon={<RotateCw className="h-4 w-4" />}
                  onClick={() => {
                    if (!retryAllFailedMutation.isPending) {
                      retryAllFailedMutation.mutate()
                    }
                  }}
                  isLoading={retryAllFailedMutation.isPending}
                  disabled={
                    retryAllFailedMutation.isPending ||
                    !isLLMSelectionComplete(retryLLM, aiProviders) ||
                    !retryClassificationReady ||
                    !isCredentialSelectionValid(
                      retryTelephonyProvider,
                      retryTelephonyIntegrationId,
                    ) ||
                    (retryTranscribeOverwrite &&
                      retryTranscribeMode === 'stt_llm' &&
                      (!retrySTT.provider || !retrySTT.model)) ||
                    (retryTranscribeOverwrite &&
                      !isLLMSelectionComplete(retryDiariserLLM, aiProviders))
                  }
                >
                  Retry {evaluation.failed_rows} row
                  {evaluation.failed_rows === 1 ? '' : 's'}
                </Button>
              </div>
            </div>
          </div>,
          document.body,
        )}

      {rerunMetricsOpen &&
        createPortal(
          (() => {
            // List every metric known on the run, sorted by name for
            // deterministic scanning. We pull from
            // ``displayMetrics`` (computed above) so the picker stays
            // in sync with what the table renders: child metrics
            // collapsed under their parent, discovered-metric
            // candidates excluded until promoted, etc.
            const pickableMetrics = (displayMetrics ?? [])
              .slice()
              .sort((a, b) => a.name.localeCompare(b.name))
            const allIds = pickableMetrics.map((m) => m.id)
            const selectedCount = rerunMetricIds.size
            const allSelected =
              allIds.length > 0 && allIds.every((id) => rerunMetricIds.has(id))
            const noneSelected = selectedCount === 0
            return (
              <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
                <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
                  <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                    <div>
                      <h2 className="text-lg font-semibold text-gray-900">
                        Re-run selected metrics
                      </h2>
                      <p className="text-xs text-gray-500 mt-0.5">
                        Pick the metrics you want to recompute. Every
                        row in this run is re-scored on just those
                        metrics; other metrics' values stay
                        byte-identical.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        if (rerunMetricsMutation.isPending) return
                        setRerunMetricsOpen(false)
                        setRerunError(null)
                      }}
                      disabled={rerunMetricsMutation.isPending}
                      className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
                      aria-label="Close re-run metrics modal"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>

                  <div className="px-6 py-5 overflow-y-auto flex-1 space-y-5">
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <label className="block text-sm font-medium text-gray-700">
                          Metrics to recompute
                        </label>
                        {pickableMetrics.length > 0 && (
                          <button
                            type="button"
                            className="text-[11px] text-primary-600 hover:text-primary-700"
                            onClick={() => {
                              if (allSelected) {
                                setRerunMetricIds(new Set())
                              } else {
                                setRerunMetricIds(new Set(allIds))
                              }
                            }}
                          >
                            {allSelected ? 'Clear all' : 'Select all'}
                          </button>
                        )}
                      </div>
                      {pickableMetrics.length === 0 ? (
                        <p className="text-sm text-gray-500 italic">
                          This run has no scored metrics yet — nothing
                          to re-run.
                        </p>
                      ) : (
                        <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-64 overflow-y-auto">
                          {pickableMetrics.map((m) => {
                            const checked = rerunMetricIds.has(m.id)
                            return (
                              <label
                                key={m.id}
                                className="flex items-start gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer"
                              >
                                <input
                                  type="checkbox"
                                  className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                                  checked={checked}
                                  onChange={(e) => {
                                    setRerunMetricIds((prev) => {
                                      const next = new Set(prev)
                                      if (e.target.checked) {
                                        next.add(m.id)
                                      } else {
                                        next.delete(m.id)
                                      }
                                      return next
                                    })
                                  }}
                                />
                                <div className="min-w-0 flex-1">
                                  <p className="text-sm font-medium text-gray-900 truncate">
                                    {m.name}
                                  </p>
                                  <p className="text-[11px] text-gray-500 font-mono truncate">
                                    {m.id}
                                  </p>
                                </div>
                              </label>
                            )
                          })}
                        </div>
                      )}
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        LLM for re-evaluation
                      </label>
                      <p className="text-xs text-gray-500 mb-2">
                        Used to score the selected metrics. Leave as-is
                        to re-run with the run's existing LLM.
                      </p>
                      {(rerunHasStandard || rerunClassificationIds.length === 0) && (
                        <ProviderModelPicker
                          kind="llm"
                          value={rerunLLM}
                          onChange={setRerunLLM}
                          allowCredentialPick
                          defaultLabel="Pick an LLM provider"
                          modelFilter={isStandardJudgeModel}
                          incompatibleHint="This credential only exposes Jev classification models, which cannot score standard metrics. Use Together Tev or a chat model instead."
                        />
                      )}
                      {rerunClassificationIds.length > 0 && (
                        <div className="mt-3">
                          <RunEvaluationClassificationModel
                            value={rerunClassificationLLM}
                            onChange={setRerunClassificationLLM}
                            metricNames={rerunClassificationIds.map((mid) => metricNameById.get(mid) ?? mid)}
                            hasCompatibleCredential={hasClassificationCredential}
                            complete={isClassificationSelectionReady(rerunClassificationLLM)}
                          />
                        </div>
                      )}
                    </div>

                    <div className="rounded-md bg-blue-50 border border-blue-200 p-3 text-xs text-blue-900">
                      Already-successful rows are eligible too — only
                      the selected metrics' scores are overwritten; the
                      rest of <code>metric_scores</code> is preserved
                      verbatim.
                    </div>

                    {rerunError && (
                      <div className="rounded-md bg-red-50 border border-red-200 p-3">
                        <div className="flex items-start gap-2">
                          <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                          <p className="text-sm text-red-800">{rerunError}</p>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-3">
                    <Button
                      variant="outline"
                      onClick={() => {
                        if (rerunMetricsMutation.isPending) return
                        setRerunMetricsOpen(false)
                        setRerunError(null)
                      }}
                      disabled={rerunMetricsMutation.isPending}
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      leftIcon={<RefreshCw className="h-4 w-4" />}
                      onClick={() => {
                        if (!rerunMetricsMutation.isPending && !noneSelected) {
                          rerunMetricsMutation.mutate()
                        }
                      }}
                      isLoading={rerunMetricsMutation.isPending}
                      disabled={
                        rerunMetricsMutation.isPending ||
                        noneSelected ||
                        !isLLMSelectionComplete(rerunLLM, aiProviders) ||
                        !rerunClassificationReady
                      }
                    >
                      Re-run {selectedCount > 0 ? `${selectedCount} ` : ''}
                      metric{selectedCount === 1 ? '' : 's'}
                    </Button>
                  </div>
                </div>
              </div>
            )
          })(),
          document.body,
        )}

    </>
  )
}
