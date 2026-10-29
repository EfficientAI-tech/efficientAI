import { Link } from 'react-router-dom'
import { AlertCircle, X } from 'lucide-react'
import Button from '../../../../components/Button'
import AIProviderModelPicker from '../../../../components/AIProviderModelPicker'
import ProviderModelPicker, {
  type ProviderModelValue,
} from '../../../../components/providers/ProviderModelPicker'
import RunEvaluationClassificationModel from '../RunEvaluationClassificationModel'
import TelephonyCredentialPicker, {
  credentialSelectionFromState,
  isCredentialSelectionValid,
} from '../TelephonyCredentialPicker'
import {
  isClassificationCapableModel,
  isClassificationMetric,
  isLLMSelectionComplete,
  isLLMSelectionPartial,
  isStandardJudgeModel,
  resolveLLMModelForSubmit,
} from '../../../../lib/llmModelOptions'
import type { CallImportEvaluationLLMOverride } from '../../../../types/api'
import { renderImportDetailModal } from './modalPortal'
import { STT_PROVIDER_ALLOWLIST } from './sttAllowlist'
import type { ImportRunEvaluationModalProps } from './importRunEvaluationModalProps'

export function ImportRunEvaluationModal(props: ImportRunEvaluationModalProps) {
  const {
  open,
  setShowRunEval,
  data,
  metrics,
  selectedMetricIds,
  setSelectedMetricIds,
  toggleMetric,
  toggleParentMetric,
  runDraftName,
  setRunDraftName,
  runEvaluationMutation,
  evalTelephonyProvider,
  setEvalTelephonyProvider,
  evalTelephonyIntegrationId,
  setEvalTelephonyIntegrationId,
  classificationLLM,
  setClassificationLLM,
  runLLM,
  setRunLLM,
  metricLLMOverrides,
  setMetricLLMOverrides,
  showAdvancedLLM,
  setShowAdvancedLLM,
  transcribeOverwrite,
  setTranscribeOverwrite,
  evalTranscribeMode,
  setEvalTranscribeMode,
  evalTranscriptSource,
  setEvalTranscriptSource,
  evalSTT,
  setEvalSTT,
  evalSTTLanguage,
  setEvalSTTLanguage,
  evalDiariserLLM,
  setEvalDiariserLLM,
  evalDiarisationPrompt,
  setEvalDiarisationPrompt,
  isManualAudioImport,
  aiProviders,
  defaultDiarisationPrompt,
  setPartialsImportError,
  setSelectedPartialId,
  setPartialsSearchInput,
  setPartialsSearchQuery,
  setPartialsImportTarget,
  openSavePartialModal,
  } = props

  return (
    <>

      {open &&
        renderImportDetailModal(
          (() => {
            const enabledMetrics = metrics.filter((m: any) => m.enabled)
            const disabledMetrics = metrics.filter((m: any) => !m.enabled)
            const allSelectableIds = enabledMetrics.flatMap((metric: any) => {
              const children: any[] = Array.isArray(metric.children)
                ? metric.children.filter((c: any) => c.enabled)
                : []
              const isParent =
                !!metric.selection_mode && children.length > 0
              if (isParent) {
                return [metric.id, ...children.map((c: any) => c.id)]
              }
              return [metric.id]
            })
            const allMetricsSelected =
              allSelectableIds.length > 0 &&
              allSelectableIds.every((metricId) =>
                selectedMetricIds.includes(metricId),
              )
            // Group the user's selection into "override targets" — one
            // entry per parent categorization metric (regardless of how
            // many of its labels are picked) and one entry per standalone
            // metric. This drives the per-metric LLM override UI: we
            // surface ONE picker per chosen metric, never one per label.
            // The picker keys overrides by parent id for hierarchical
            // metrics; the backend already accepts parent ids and
            // expands them to every child of that parent.
            type OverrideTarget = {
              id: string
              name: string
              isHierarchical: boolean
              selectedChildCount: number
            }
            const selectedSet = new Set(selectedMetricIds)
            const overrideTargets: OverrideTarget[] = []
            for (const metric of enabledMetrics as any[]) {
              const children: any[] = Array.isArray(metric.children)
                ? metric.children.filter((c: any) => c.enabled)
                : []
              const isHierarchical =
                !!metric.selection_mode && children.length > 0
              if (isHierarchical) {
                const selectedChildCount = children.filter((c: any) =>
                  selectedSet.has(c.id),
                ).length
                if (selectedChildCount > 0) {
                  overrideTargets.push({
                    id: metric.id,
                    name: metric.name,
                    isHierarchical: true,
                    selectedChildCount,
                  })
                }
              } else if (selectedSet.has(metric.id)) {
                overrideTargets.push({
                  id: metric.id,
                  name: metric.name,
                  isHierarchical: false,
                  selectedChildCount: 0,
                })
              }
            }
            const overrideTargetIds = new Set(
              overrideTargets.map((t) => t.id),
            )
            // Classification metrics are scored only by System 1 (Jev) models;
            // standard metrics only by regular LLM judges. Split the selection so
            // each group gets a compatible model picker.
            const classificationTargetIds = new Set(
              enabledMetrics
                .filter(
                  (m) =>
                    isClassificationMetric(
                      m as Parameters<typeof isClassificationMetric>[0],
                    ) && overrideTargetIds.has(m.id),
                )
                .map((m) => m.id as string),
            )
            const classificationTargets = overrideTargets.filter((t) =>
              classificationTargetIds.has(t.id),
            )
            const standardTargetCount =
              overrideTargets.length - classificationTargets.length
            const hasClassificationSelected = classificationTargets.length > 0
            const hasStandardSelected = standardTargetCount > 0
            const classificationLLMComplete =
              aiProviders.length > 0 &&
              isLLMSelectionComplete(classificationLLM, aiProviders) &&
              isClassificationCapableModel(
                resolveLLMModelForSubmit(classificationLLM, aiProviders) ??
                  classificationLLM.model ??
                  '',
              )
            const runError = runEvaluationMutation.isError
              ? (runEvaluationMutation.error as any)?.response?.data?.detail ||
                'Failed to start evaluation.'
              : null
            return (
              <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
                <div className="bg-white rounded-lg shadow-xl max-w-5xl w-full mx-4">
                  <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <h3 className="text-lg font-semibold">Run Evaluation</h3>
                    <button
                      onClick={() => {
                        if (runEvaluationMutation.isPending) return
                        setShowRunEval(false)
                      }}
                      className="text-gray-400 hover:text-gray-600"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  <div className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm text-gray-600">
                        Fetches recordings, diarizes, and scores each row in this
                        batch. Pick metrics and models below
                        {data.status === 'mapped'
                          ? ', plus telephony credentials for recording fetch.'
                          : '.'}
                      </p>
                      <Link
                        to="/metrics-management"
                        className="text-xs font-medium text-primary-700 hover:text-primary-900 whitespace-nowrap"
                      >
                        Manage metrics →
                      </Link>
                    </div>

                    <div>
                      <label
                        htmlFor="run-eval-name"
                        className="block text-xs font-medium text-gray-700 mb-1"
                      >
                        Name this run{' '}
                        <span className="text-gray-400 font-normal">(optional)</span>
                      </label>
                      <input
                        id="run-eval-name"
                        type="text"
                        value={runDraftName}
                        onChange={(e) => setRunDraftName(e.target.value)}
                        placeholder="e.g. March QA pass"
                        maxLength={255}
                        disabled={runEvaluationMutation.isPending}
                        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:opacity-60"
                      />
                      <p className="mt-1 text-[11px] text-gray-500">
                        Leave blank to fall back to the run's UUID prefix.
                      </p>
                    </div>

                    {data.status === 'mapped' && (
                      <div className="rounded-lg border border-gray-200 bg-gray-50/80 p-4 space-y-3">
                        <div>
                          <h4 className="text-sm font-semibold text-gray-900">
                            Recording fetch
                          </h4>
                          <p className="text-xs text-gray-600 mt-0.5">
                            Credentials used to download each row&apos;s recording as
                            part of this evaluation run.
                          </p>
                        </div>
                        <TelephonyCredentialPicker
                          selectedProvider={evalTelephonyProvider}
                          selectedIntegrationId={evalTelephonyIntegrationId}
                          onProviderChange={setEvalTelephonyProvider}
                          onIntegrationChange={setEvalTelephonyIntegrationId}
                          disabled={runEvaluationMutation.isPending}
                          compact
                        />
                      </div>
                    )}

                    {enabledMetrics.length === 0 ? (
                      <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 space-y-2">
                        <p className="font-medium">No enabled agent metrics yet.</p>
                        <p>
                          Evaluations only run against metrics that are <strong>enabled</strong> on
                          your organization and support the <strong>agent</strong> surface.
                        </p>
                        {disabledMetrics.length > 0 ? (
                          <p>
                            You have {disabledMetrics.length} disabled metric
                            {disabledMetrics.length === 1 ? '' : 's'} (
                            {disabledMetrics
                              .slice(0, 3)
                              .map((m: any) => m.name)
                              .join(', ')}
                            {disabledMetrics.length > 3 ? ', …' : ''}). Open Metrics to enable
                            them.
                          </p>
                        ) : (
                          <p>You don't have any metrics yet — create one in Metrics first.</p>
                        )}
                        <Link
                          to="/metrics-management"
                          className="inline-block font-medium text-amber-900 underline hover:text-amber-700"
                        >
                          Open Metrics →
                        </Link>
                      </div>
                    ) : (
                      <>
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
                        <div className="space-y-3">
                        <div className="space-y-2">
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-xs uppercase tracking-wide font-semibold text-gray-500">
                              Enabled metrics ({enabledMetrics.length})
                              <span
                                className="ml-1 text-red-600 normal-case"
                                aria-label="required"
                                title="At least one metric is required"
                              >
                                *
                              </span>
                            </p>
                            <div className="flex items-center gap-2">
                              {enabledMetrics.length > 0 && (
                                <button
                                  type="button"
                                  className="text-[11px] text-primary-600 hover:text-primary-700 disabled:opacity-50"
                                  disabled={runEvaluationMutation.isPending}
                                  onClick={() => {
                                    if (allMetricsSelected) {
                                      setSelectedMetricIds([])
                                    } else {
                                      setSelectedMetricIds(allSelectableIds)
                                    }
                                  }}
                                >
                                  {allMetricsSelected ? 'Clear all' : 'Select all'}
                                </button>
                              )}
                              {selectedMetricIds.length === 0 ? (
                                <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-inset ring-amber-200">
                                  <AlertCircle className="h-3 w-3" />
                                  Pick at least one
                                </span>
                              ) : (
                                <span className="text-[10px] font-medium text-gray-500">
                                  {selectedMetricIds.length} selected
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-64 overflow-y-auto">
                          {enabledMetrics.map((metric: any) => {
                            const children: any[] = Array.isArray(metric.children)
                              ? metric.children.filter((c: any) => c.enabled)
                              : []
                            const isParent =
                              !!metric.selection_mode && children.length > 0
                            if (!isParent) {
                              return (
                                <label
                                  key={metric.id}
                                  className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm"
                                >
                                  <input
                                    type="checkbox"
                                    checked={selectedMetricIds.includes(metric.id)}
                                    onChange={() => toggleMetric(metric.id)}
                                    disabled={runEvaluationMutation.isPending}
                                    className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                                  />
                                  <span className="font-medium text-gray-900 truncate">
                                    {metric.name}
                                  </span>
                                </label>
                              )
                            }
                            const childIds = children.map((c) => c.id)
                            const selectedChildCount = childIds.filter((cid) =>
                              selectedMetricIds.includes(cid),
                            ).length
                            const allChildrenSelected =
                              selectedChildCount === childIds.length &&
                              childIds.length > 0
                            const someChildrenSelected =
                              selectedChildCount > 0 && !allChildrenSelected
                            return (
                              <label
                                key={metric.id}
                                className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm"
                              >
                                <input
                                  type="checkbox"
                                  ref={(el) => {
                                    if (el) {
                                      el.indeterminate = someChildrenSelected
                                    }
                                  }}
                                  checked={allChildrenSelected}
                                  onChange={() => toggleParentMetric(metric)}
                                  disabled={runEvaluationMutation.isPending}
                                  className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                                />
                                <span className="min-w-0 flex-1 flex items-baseline gap-2">
                                  <span className="font-medium text-gray-900 truncate">
                                    {metric.name}
                                  </span>
                                  {someChildrenSelected ? (
                                    <span className="text-[11px] text-gray-500 whitespace-nowrap">
                                      {selectedChildCount}/{childIds.length} labels
                                    </span>
                                  ) : null}
                                </span>
                              </label>
                            )
                          })}
                          </div>
                        </div>

                        {disabledMetrics.length > 0 && (
                          <details className="rounded-md border border-gray-200 bg-gray-50 p-3 text-sm">
                            <summary className="cursor-pointer font-medium text-gray-700">
                              {disabledMetrics.length} disabled metric
                              {disabledMetrics.length === 1 ? '' : 's'} hidden
                            </summary>
                            <ul className="mt-2 space-y-1 text-xs text-gray-600">
                              {disabledMetrics.map((metric: any) => (
                                <li key={metric.id} className="flex items-baseline gap-2">
                                  <span className="line-through">{metric.name}</span>
                                  <span className="text-gray-400">— disabled</span>
                                </li>
                              ))}
                            </ul>
                            <Link
                              to="/metrics-management"
                              className="mt-2 inline-block text-xs font-medium text-primary-700 hover:text-primary-900"
                            >
                              Enable them in Metrics →
                            </Link>
                          </details>
                        )}
                        </div>

                        <div className="space-y-3">
                        {hasClassificationSelected && (
                          <RunEvaluationClassificationModel
                            value={classificationLLM}
                            onChange={setClassificationLLM}
                            metricNames={classificationTargets.map((t) => t.name)}
                            hasCompatibleCredential={aiProviders.some(
                              (p) =>
                                p.is_active &&
                                (p.enabled_models?.some?.((m: string) => isClassificationCapableModel(m)) ||
                                  isClassificationCapableModel(p.gateway_model ?? '') ||
                                  ['openrouter', 'typesafe'].includes(String(p.provider).toLowerCase())),
                            )}
                            complete={classificationLLMComplete}
                          />
                        )}
                        {/* Run-level LLM config */}
                        {(() => {
                          const llmPartial =
                            aiProviders.length > 0 &&
                            isLLMSelectionPartial(runLLM, aiProviders)
                          return (
                            <div
                              className={`rounded-md border p-3 space-y-2 ${
                                llmPartial
                                  ? 'border-red-300 bg-red-50/40'
                                  : 'border-gray-200 bg-gray-50'
                              }`}
                            >
                              <p className="text-xs uppercase tracking-wide font-semibold text-gray-500">
                                {hasClassificationSelected ? 'Evaluation LLM · standard metrics' : 'Evaluation LLM'}
                              </p>
                              <p className="text-[11px] text-gray-500">
                                {hasClassificationSelected && !hasStandardSelected
                                  ? 'Only classification metrics are selected — they use the System 1 model above. Pick an LLM here only if you add standard metrics.'
                                  : hasClassificationSelected
                                    ? `Scores the ${standardTargetCount} standard metric${standardTargetCount === 1 ? '' : 's'}. Jev (classification) models are hidden here; Together Tev models are available. Leave empty to keep the default (OpenAI · gpt-4o).`
                                    : 'Pick the LLM that scores every selected metric. Leave empty to keep the default (OpenAI · gpt-4o).'}
                              </p>
                              <AIProviderModelPicker
                                provider={runLLM.provider ?? ''}
                                model={runLLM.model ?? ''}
                                credentialId={runLLM.credential_id ?? ''}
                                modelFilter={isStandardJudgeModel}
                                incompatibleHint="This credential only exposes Jev classification models, which cannot score standard metrics. Use Together Tev or a chat model instead."
                                onSelectionChange={(next) =>
                                  setRunLLM((prev) => ({
                                    ...prev,
                                    provider: next.provider || null,
                                    model: next.model || null,
                                    credential_id: next.credentialId || null,
                                  }))
                                }
                                onProviderChange={(next) =>
                                  setRunLLM((prev) => ({
                                    ...prev,
                                    provider: next || null,
                                  }))
                                }
                                onCredentialIdChange={(next) =>
                                  setRunLLM((prev) => ({
                                    ...prev,
                                    credential_id: next || null,
                                  }))
                                }
                                onModelChange={(next) =>
                                  setRunLLM((prev) => ({
                                    ...prev,
                                    model: next || null,
                                  }))
                                }
                                llm_config={runLLM.llm_config ?? null}
                                onLLMConfigChange={(llm_config) =>
                                  setRunLLM((prev) => ({ ...prev, llm_config }))
                                }
                              />
                              {llmPartial && (
                                <p className="flex items-start gap-1 text-[11px] font-medium text-red-700">
                                  <AlertCircle className="h-3 w-3 mt-0.5 flex-shrink-0" />
                                  <span>
                                    {runLLM.provider || runLLM.credential_id
                                      ? 'Pick a complete LLM credential (including Custom gateway models), or clear the selection to use the default.'
                                      : 'Pick a provider for this model, or clear the model to use the default.'}
                                  </span>
                                </p>
                              )}

                          {overrideTargets.length > 0 && (
                            <div className="pt-2 border-t border-gray-200">
                              <button
                                type="button"
                                onClick={() => setShowAdvancedLLM((s) => !s)}
                                className="text-[11px] font-medium text-primary-700 hover:text-primary-900"
                              >
                                {showAdvancedLLM ? 'Hide' : 'Show'} per-metric overrides
                                ({overrideTargets.length} metric
                                {overrideTargets.length === 1 ? '' : 's'})
                              </button>
                              {showAdvancedLLM && (
                                <div className="mt-2 space-y-3">
                                  {overrideTargets.map((target) => {
                                    const override = metricLLMOverrides[
                                      target.id
                                    ] || {
                                      provider: null,
                                      model: null,
                                      credential_id: null,
                                    }
                                    const updateOverride = (
                                      patch: Partial<ProviderModelValue>,
                                    ) => {
                                      setMetricLLMOverrides((prev) => {
                                        const copy = { ...prev }
                                        const existing =
                                          copy[target.id] || {
                                            provider: null,
                                            model: null,
                                            credential_id: null,
                                          }
                                        const updated: ProviderModelValue = {
                                          ...existing,
                                          ...patch,
                                        }
                                        const cleared =
                                          !updated.provider &&
                                          !updated.model?.trim() &&
                                          !updated.credential_id &&
                                          !updated.llm_config
                                        if (cleared) {
                                          delete copy[target.id]
                                        } else {
                                          copy[target.id] = updated
                                        }
                                        return copy
                                      })
                                    }
                                    return (
                                      <div
                                        key={target.id}
                                        className="rounded border border-gray-200 bg-white p-2"
                                      >
                                        <p className="text-xs font-medium text-gray-800 mb-1">
                                          {target.name}
                                          {target.isHierarchical && (
                                            <span className="ml-2 text-[10px] font-normal text-gray-500">
                                              ({target.selectedChildCount} label
                                              {target.selectedChildCount === 1
                                                ? ''
                                                : 's'}{' '}
                                              selected)
                                            </span>
                                          )}
                                        </p>
                                        <AIProviderModelPicker
                                          provider={override.provider ?? ''}
                                          model={override.model ?? ''}
                                          credentialId={override.credential_id ?? ''}
                                          modelFilter={
                                            classificationTargetIds.has(target.id)
                                              ? isClassificationCapableModel
                                              : isStandardJudgeModel
                                          }
                                          onProviderChange={(next) =>
                                            updateOverride({
                                              provider: next || null,
                                            })
                                          }
                                          onCredentialIdChange={(next) =>
                                            updateOverride({
                                              credential_id: next || null,
                                            })
                                          }
                                          onModelChange={(next) =>
                                            updateOverride({ model: next || null })
                                          }
                                          onLLMConfigChange={(llm_config) =>
                                            updateOverride({ llm_config })
                                          }
                                          llm_config={override.llm_config ?? null}
                                          size="sm"
                                        />
                                      </div>
                                    )
                                  })}
                                </div>
                              )}
                            </div>
                          )}
                            </div>
                          )
                        })()}

                        <div className="rounded-md border border-gray-200 bg-gray-50 p-3 space-y-3">
                          <div>
                            <p className="text-sm font-medium text-gray-900">
                              Transcript for evaluation
                            </p>
                            <p className="text-[11px] text-gray-500 mt-0.5">
                              {isManualAudioImport
                                ? 'Recordings are already uploaded to this batch. Diarization uses the stored audio files — no CSV recording URL column is needed.'
                                : 'Choose whether to score the CSV production transcript or diarize first, then score the diarized output.'}
                            </p>
                          </div>
                          <div
                            role="tablist"
                            aria-label="Evaluation transcript source"
                            className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5"
                          >
                            <button
                              type="button"
                              role="tab"
                              aria-pressed={evalTranscriptSource === 'diarised'}
                              onClick={() => setEvalTranscriptSource('diarised')}
                              className={`px-3 py-1.5 text-[11px] font-medium rounded-md transition ${
                                evalTranscriptSource === 'diarised'
                                  ? 'bg-primary-50 text-primary-700 ring-1 ring-inset ring-primary-200'
                                  : 'text-gray-600 hover:text-gray-900'
                              }`}
                            >
                              Diarize then evaluate
                            </button>
                            <button
                              type="button"
                              role="tab"
                              aria-pressed={evalTranscriptSource === 'production'}
                              onClick={() =>
                                setEvalTranscriptSource('production')
                              }
                              className={`px-3 py-1.5 text-[11px] font-medium rounded-md transition ${
                                evalTranscriptSource === 'production'
                                  ? 'bg-primary-50 text-primary-700 ring-1 ring-inset ring-primary-200'
                                  : 'text-gray-600 hover:text-gray-900'
                              }`}
                            >
                              Use production transcript
                            </button>
                          </div>
                          {evalTranscriptSource === 'production' ? (
                            <p className="text-[11px] text-gray-500">
                              Skips diarization and recording download, and
                              scores the transcript imported from your CSV
                              directly. Audio metrics require a recording
                              already stored on the row.
                            </p>
                          ) : null}
                        </div>

                        {evalTranscriptSource === 'diarised' &&
                        (() => {
                          // In ``llm_only`` mode there is no STT —
                          // the diariser LLM consumes the audio
                          // directly. We adapt the "is the auto-
                          // diarise step ready?" check to reflect
                          // that so the banner doesn't yell about a
                          // missing STT picker that's intentionally
                          // hidden.
                          const sttMissing =
                            evalTranscribeMode === 'stt_llm' &&
                            (!evalSTT.provider || !evalSTT.model)
                          const diariserMissing = !isLLMSelectionComplete(
                            evalDiariserLLM,
                            aiProviders,
                          )
                          const sectionIncomplete = sttMissing || (
                            evalTranscribeMode === 'llm_only' && diariserMissing
                          )
                          return (
                            <div
                              className={`rounded-md border p-3 space-y-2 ${
                                sectionIncomplete
                                  ? 'border-red-300 bg-red-50/40 ring-1 ring-red-200'
                                  : 'border-gray-200 bg-gray-50'
                              }`}
                            >
                              <label className="flex items-start gap-2 text-sm">
                                <input
                                  type="checkbox"
                                  checked
                                  disabled
                                  readOnly
                                  className="mt-0.5"
                                  aria-label="Auto-diarise rows missing a diarised transcript (always on)"
                                />
                                <span className="flex-1">
                                  <span className="flex items-center gap-2 flex-wrap">
                                    <span className="font-medium text-gray-900">
                                      Auto-diarise rows missing a diarised
                                      transcript
                                    </span>
                                    <span
                                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
                                        sectionIncomplete
                                          ? 'bg-red-100 text-red-700 ring-1 ring-inset ring-red-200'
                                          : 'bg-green-50 text-green-700 ring-1 ring-inset ring-green-200'
                                      }`}
                                    >
                                      {sectionIncomplete ? 'Required' : 'Set'}
                                    </span>
                                  </span>
                                  <span className="block text-[11px] text-gray-500">
                                    {evalTranscribeMode === 'stt_llm'
                                      ? "Rows that don't already have a diarised transcript are diarised first via the STT provider you pick below."
                                      : "Rows that don't already have a diarised transcript are diarised by feeding the audio directly to the multimodal LLM you pick below. Calls longer than about 8 minutes need enough output headroom—if results look cut off, use STT + LLM diariser instead."}
                                  </span>
                                </span>
                              </label>
                              <div className="pl-6 space-y-2">
                                {/* Mode toggle. Hidden behind the
                                    "Auto-diarise" checkbox row so the
                                    flow reads top-to-bottom: enable
                                    auto-diarise → pick pipeline → pick
                                    models. */}
                                {/* Same ordering rationale as the
                                    standalone Transcribe modal:
                                    LLM-only is the recommended default
                                    and STT+LLM is the advanced
                                    fallback. */}
                                <div
                                  role="tablist"
                                  aria-label="Auto-diarise pipeline"
                                  className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5"
                                >
                                  <button
                                    type="button"
                                    role="tab"
                                    aria-pressed={evalTranscribeMode === 'llm_only'}
                                    onClick={() =>
                                      setEvalTranscribeMode('llm_only')
                                    }
                                    className={`px-3 py-1 text-[11px] font-medium rounded-md transition ${
                                      evalTranscribeMode === 'llm_only'
                                        ? 'bg-primary-50 text-primary-700 ring-1 ring-inset ring-primary-200'
                                        : 'text-gray-600 hover:text-gray-900'
                                    }`}
                                  >
                                    LLM only (audio in)
                                  </button>
                                  <button
                                    type="button"
                                    role="tab"
                                    aria-pressed={evalTranscribeMode === 'stt_llm'}
                                    onClick={() =>
                                      setEvalTranscribeMode('stt_llm')
                                    }
                                    className={`px-3 py-1 text-[11px] font-medium rounded-md transition inline-flex items-center gap-1.5 ${
                                      evalTranscribeMode === 'stt_llm'
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
                                {evalTranscribeMode === 'stt_llm' && (
                                  <>
                                    <ProviderModelPicker
                                      kind="stt"
                                      value={evalSTT}
                                      onChange={setEvalSTT}
                                      providerAllowList={STT_PROVIDER_ALLOWLIST}
                                      defaultLabel="Pick an STT provider"
                                      allowCredentialPick
                                    />
                                    {sttMissing && (
                                      <p className="flex items-start gap-1 text-[11px] font-medium text-red-700">
                                        <AlertCircle className="h-3 w-3 mt-0.5 flex-shrink-0" />
                                        <span>
                                          {!evalSTT.provider
                                            ? 'Pick an STT provider — auto-diarisation is mandatory for every run.'
                                            : 'Pick a model for this STT provider to enable the run.'}
                                        </span>
                                      </p>
                                    )}
                                    <input
                                      type="text"
                                      value={evalSTTLanguage}
                                      onChange={(e) =>
                                        setEvalSTTLanguage(e.target.value)
                                      }
                                      placeholder="Language hint (e.g. en, hi)"
                                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                                    />
                                  </>
                                )}
                                <label className="flex items-start gap-2 text-xs">
                                  <input
                                    type="checkbox"
                                    checked={transcribeOverwrite}
                                    onChange={(e) =>
                                      setTranscribeOverwrite(e.target.checked)
                                    }
                                  />
                                  <span>
                                    Overwrite existing diarised transcripts
                                    (otherwise rows with a stored transcript
                                    are reused).
                                  </span>
                                </label>
                                <div className="pt-3 border-t border-gray-200 space-y-2">
                                  <p className="text-xs font-medium text-gray-700">
                                    {evalTranscribeMode === 'stt_llm'
                                      ? 'Diariser LLM'
                                      : 'Multimodal diariser LLM'}
                                  </p>
                                  <p className="text-[11px] text-gray-500">
                                    {evalTranscribeMode === 'stt_llm'
                                      ? 'After the STT step, this chat model splits the plain transcript into agent / user turns using the prompt below.'
                                      : 'This chat model receives the audio bytes and the prompt and produces structured agent / user turns in one call. Pick a model that accepts audio input (e.g. Gemini 1.5/2.0 or GPT-4o audio-preview).'}
                                  </p>
                                  <ProviderModelPicker
                                    kind="llm"
                                    value={evalDiariserLLM}
                                    onChange={setEvalDiariserLLM}
                                    defaultLabel="Pick an LLM for diarisation"
                                    allowCredentialPick
                                    audioCapableOnly={evalTranscribeMode === 'llm_only'}
                                  />
                                  <div className="flex items-center justify-between pt-1">
                                    <label className="text-[11px] font-medium text-gray-700">
                                      Diarisation prompt
                                    </label>
                                    <div className="flex items-center gap-3">
                                      <button
                                        type="button"
                                        onClick={() => {
                                          setPartialsImportError(null)
                                          setSelectedPartialId('')
                                          setPartialsSearchInput('')
                                          setPartialsSearchQuery('')
                                          setPartialsImportTarget('eval')
                                        }}
                                        className="text-[11px] text-primary-600 hover:text-primary-700"
                                      >
                                        Import from saved partials
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() =>
                                          openSavePartialModal('eval')
                                        }
                                        disabled={
                                          !evalDiarisationPrompt.trim()
                                        }
                                        title={
                                          evalDiarisationPrompt.trim()
                                            ? 'Save the current prompt to your Prompt Partials library'
                                            : 'Enter or import a prompt first'
                                        }
                                        className="text-[11px] text-primary-600 hover:text-primary-700 disabled:text-gray-400 disabled:cursor-not-allowed"
                                      >
                                        Save as partial
                                      </button>
                                      {defaultDiarisationPrompt && (
                                        <button
                                          type="button"
                                          onClick={() =>
                                            setEvalDiarisationPrompt(
                                              defaultDiarisationPrompt,
                                            )
                                          }
                                          className="text-[11px] text-primary-600 hover:text-primary-700"
                                        >
                                          Reset to default
                                        </button>
                                      )}
                                    </div>
                                  </div>
                                  <textarea
                                    value={evalDiarisationPrompt}
                                    onChange={(e) =>
                                      setEvalDiarisationPrompt(e.target.value)
                                    }
                                    rows={6}
                                    placeholder={
                                      defaultDiarisationPrompt ||
                                      'Describe how the LLM should split the transcript into agent / user turns…'
                                    }
                                    className="w-full px-3 py-2 text-[11px] font-mono border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                                  />
                                  <p className="text-[11px] text-gray-500">
                                    Leave blank to fall back to the
                                    canonical default prompt.
                                  </p>
                                </div>
                              </div>
                            </div>
                          )
                        })()}
                        </div>
                        </div>
                      </>
                    )}

                    {runError ? (
                      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 space-y-1">
                        <p>{runError}</p>
                        {/metric/i.test(runError) ? (
                          <Link
                            to="/metrics-management"
                            className="font-medium text-red-700 underline hover:text-red-900"
                          >
                            Check your metrics setup →
                          </Link>
                        ) : null}
                      </div>
                    ) : null}

                    {(() => {
                      const disabledReasons: string[] = []
                      if (data.status === 'mapped') {
                        if (
                          !isCredentialSelectionValid(
                            evalTelephonyProvider,
                            evalTelephonyIntegrationId,
                          )
                        ) {
                          disabledReasons.push(
                            'Pick telephony credentials (or direct URL) for recording fetch.',
                          )
                        }
                      }
                      if (enabledMetrics.length === 0) {
                        disabledReasons.push(
                          'Enable at least one agent metric in Metrics.',
                        )
                      } else if (selectedMetricIds.length === 0) {
                        disabledReasons.push('Select at least one metric to score.')
                      }
                      if (hasClassificationSelected && !classificationLLMComplete) {
                        disabledReasons.push(
                          'Pick a System 1 (Jev) model for the classification metrics.',
                        )
                      }
                      // STT and diariser are only required when diarising.
                      if (evalTranscriptSource === 'diarised') {
                        if (evalTranscribeMode === 'stt_llm') {
                          if (!evalSTT.provider) {
                            disabledReasons.push(
                              'Pick an STT provider (auto-diarisation is required).',
                            )
                          } else if (!evalSTT.model) {
                            disabledReasons.push(
                              'Pick an STT model for the selected provider.',
                            )
                          }
                        }
                        if (!isLLMSelectionComplete(evalDiariserLLM, aiProviders)) {
                          disabledReasons.push(
                            evalTranscribeMode === 'llm_only'
                              ? 'Pick a multimodal LLM provider — the recording is fed to it directly in LLM-only mode.'
                              : 'Pick a diariser LLM provider and model (or a Custom gateway credential).',
                          )
                        }
                      }
                      if (
                        aiProviders.length > 0 &&
                        isLLMSelectionPartial(runLLM, aiProviders)
                      ) {
                        disabledReasons.push(
                          'Finish the Evaluation LLM selection (pick a provider and model, or a Custom gateway credential, or clear both to use the default).',
                        )
                      }
                      const isDisabled =
                        disabledReasons.length > 0 ||
                        runEvaluationMutation.isPending
                      return (
                        <>
                          {disabledReasons.length > 0 && (
                            <div
                              role="status"
                              className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
                            >
                              <p className="flex items-center gap-1.5 font-medium">
                                <AlertCircle className="h-4 w-4" />
                                Finish the required fields to start this run
                              </p>
                              <ul className="mt-1 list-disc pl-7 space-y-0.5 text-[12px]">
                                {disabledReasons.map((reason) => (
                                  <li key={reason}>{reason}</li>
                                ))}
                              </ul>
                            </div>
                          )}

                          <div className="flex gap-2 pt-2">
                            <Button
                              variant="outline"
                              onClick={() => setShowRunEval(false)}
                              disabled={runEvaluationMutation.isPending}
                              className="flex-1"
                            >
                              Cancel
                            </Button>
                            <Button
                              variant="primary"
                              isLoading={runEvaluationMutation.isPending}
                              disabled={isDisabled}
                              title={
                                disabledReasons.length > 0
                                  ? `Can't start yet:\n• ${disabledReasons.join('\n• ')}`
                                  : 'Start this evaluation run'
                              }
                        onClick={() => {
                          // Build a clean overrides payload — drop any
                          // entries that didn't end up with a complete
                          // LLM selection so the API doesn't 400 on
                          // partial fills. We also discard entries for
                          // ids that are no longer in ``overrideTargets``
                          // (e.g., the user set an override for a parent
                          // then deselected every one of its labels) so
                          // stale state doesn't trip backend validation.
                          const overrides: Record<
                            string,
                            CallImportEvaluationLLMOverride
                          > = {}
                          for (const [mid, val] of Object.entries(
                            metricLLMOverrides,
                          )) {
                            if (!overrideTargetIds.has(mid)) continue
                            if (isLLMSelectionComplete(val, aiProviders)) {
                              overrides[mid] = {
                                provider: val.provider!,
                                model:
                                  resolveLLMModelForSubmit(val, aiProviders) ??
                                  val.model!,
                                credential_id: val.credential_id || null,
                                llm_config: val.llm_config || null,
                              }
                            } else if (val.llm_config) {
                              overrides[mid] = {
                                llm_config: val.llm_config,
                              }
                            }
                          }
                          // Classification metrics always run on the System 1 model unless
                          // the user picked a per-metric override for them.
                          const runLevelLLM =
                            hasClassificationSelected && !hasStandardSelected
                              ? classificationLLM
                              : runLLM
                          if (hasClassificationSelected && hasStandardSelected) {
                            for (const target of classificationTargets) {
                              if (overrides[target.id]?.provider) continue
                              overrides[target.id] = {
                                provider: classificationLLM.provider,
                                model:
                                  resolveLLMModelForSubmit(classificationLLM, aiProviders) ??
                                  classificationLLM.model,
                                credential_id: classificationLLM.credential_id,
                                llm_config: classificationLLM.llm_config,
                              }
                            }
                          }
                          const runLLMComplete = isLLMSelectionComplete(
                            runLevelLLM,
                            aiProviders,
                          )
                          runEvaluationMutation.mutate({
                            metric_ids: selectedMetricIds,
                            name: runDraftName.trim() || null,
                            transcript_sources: [evalTranscriptSource],
                            llm_provider: runLLMComplete
                              ? runLevelLLM.provider || null
                              : null,
                            llm_model: runLLMComplete
                              ? resolveLLMModelForSubmit(runLevelLLM, aiProviders) ??
                                runLevelLLM.model ??
                                null
                              : null,
                            llm_credential_id: runLLMComplete
                              ? runLevelLLM.credential_id || null
                              : null,
                            llm_config: runLLMComplete
                              ? runLevelLLM.llm_config || null
                              : null,
                            metric_llm_overrides: Object.keys(overrides).length
                              ? overrides
                              : null,
                            auto_transcribe: evalTranscriptSource === 'diarised',
                            ...(evalTranscriptSource === 'diarised'
                              ? {
                                  transcribe_overwrite: transcribeOverwrite,
                                  transcribe_mode: evalTranscribeMode,
                                  stt_provider:
                                    evalTranscribeMode === 'stt_llm'
                                      ? evalSTT.provider
                                      : null,
                                  stt_model:
                                    evalTranscribeMode === 'stt_llm'
                                      ? evalSTT.model
                                      : null,
                                  stt_credential_id:
                                    evalTranscribeMode === 'stt_llm'
                                      ? evalSTT.credential_id || null
                                      : null,
                                  stt_language:
                                    evalTranscribeMode === 'stt_llm'
                                      ? evalSTTLanguage.trim() || null
                                      : null,
                                  diarization_llm_provider:
                                    evalDiariserLLM.provider,
                                  diarization_llm_model:
                                    resolveLLMModelForSubmit(
                                      evalDiariserLLM,
                                      aiProviders,
                                    ) ?? evalDiariserLLM.model,
                                  diarization_llm_credential_id:
                                    evalDiariserLLM.credential_id || null,
                                  diarization_prompt:
                                    evalDiarisationPrompt.trim() || null,
                                }
                              : {}),
                            discover_new_metrics: false,
                            ...(data.status === 'mapped'
                              ? (() => {
                                  const cred = credentialSelectionFromState(
                                    evalTelephonyProvider,
                                    evalTelephonyIntegrationId,
                                  )
                                  return {
                                    provider: cred.provider,
                                    telephony_integration_id:
                                      cred.telephonyIntegrationId,
                                  }
                                })()
                              : {}),
                          })
                        }}
                              className="flex-1"
                            >
                              Start
                            </Button>
                          </div>
                        </>
                      )
                    })()}
                  </div>
                </div>
              </div>
            )
          })(),
        )}
    </>
  )
}
