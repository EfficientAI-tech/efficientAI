import {
  AlertCircle,
  Check,
  Mic,
  RefreshCw,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import Button from '../../../../components/Button'
import ProviderModelPicker from '../../../../components/providers/ProviderModelPicker'
import { isLLMSelectionComplete } from '../../../../lib/llmModelOptions'
import type { CallImportRow } from '../../../../types/api'
import { renderImportDetailModal } from './modalPortal'
import { STT_PROVIDER_ALLOWLIST } from './sttAllowlist'
import type { ImportTranscribeModalsProps } from './importTranscribeModalsProps'

export function ImportTranscribeModals(props: ImportTranscribeModalsProps) {
  const {
  partialsImportTarget,
  closePartialsImportModal,
  importPartialMutation,
  partialsSearchInput,
  setPartialsSearchInput,
  isLoadingPartials,
  promptPartials,
  partialsSearchQuery,
  selectedPartialId,
  setSelectedPartialId,
  partialsImportError,
  savePartialTarget,
  closeSavePartialModal,
  savePartialMutation,
  savePartialMode,
  setSavePartialMode,
  setSavePartialError,
  transcribeDiarisationPrompt,
  evalDiarisationPrompt,
  savePartialName,
  setSavePartialName,
  savePartialDescription,
  setSavePartialDescription,
  savePartialExistingId,
  setSavePartialExistingId,
  savePartialChangeSummary,
  setSavePartialChangeSummary,
  savePartialError,
  savePartialSuccess,
  showTranscribeModal,
  transcribeTargetRows,
  bulkSelectionFilter,
  selectedCount,
  transcribeMode,
  setTranscribeMode,
  transcribeSTT,
  setTranscribeSTT,
  transcribeLanguage,
  setTranscribeLanguage,
  transcribeDiariserLLM,
  setTranscribeDiariserLLM,
  aiProviders,
  defaultDiarisationPrompt,
  openSavePartialModal,
  setPartialsImportError,
  setPartialsSearchQuery,
  setPartialsImportTarget,
  setTranscribeDiarisationPrompt,
  transcribeOverwriteStandalone,
  setTranscribeOverwriteStandalone,
  transcribeError,
  transcribeRowsMutation,
  setShowTranscribeModal,
  setTranscribeTargetRows,
  showBulkActionsModal,
  setShowBulkActionsModal,
  bulkActionError,
  setBulkActionError,
  bulkActionResult,
  setBulkActionResult,
  selectionSpansPages,
  transcribeReadySelection,
  openTranscribeModal,
  selectedRowIds,
  bulkCancelDiarisationMutation,
  cancellableSelection,
  setBulkDeleteRowsError,
  setShowBulkDeleteRows,
  } = props

  return (
    <>

{partialsImportTarget !== null &&
        renderImportDetailModal(
          <div
            className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[10000]"
            onClick={closePartialsImportModal}
          >
            <div
              className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[85vh] overflow-hidden flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <h3 className="text-lg font-semibold text-gray-900">
                  Import diarisation prompt from saved partials
                </h3>
                <button
                  onClick={closePartialsImportModal}
                  className="text-gray-400 hover:text-gray-600"
                  aria-label="Close prompt partials modal"
                  disabled={importPartialMutation.isPending}
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6 space-y-4 overflow-y-auto flex-1">
                <p className="text-xs text-gray-500">
                  Pick a saved Prompt Partial; its content will replace
                  the current diarisation prompt textarea.
                </p>
                <input
                  type="text"
                  value={partialsSearchInput}
                  onChange={(e) => setPartialsSearchInput(e.target.value)}
                  placeholder="Search saved prompts..."
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />

                {isLoadingPartials ? (
                  <div className="flex items-center justify-center py-8 text-sm text-gray-500">
                    <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                    Loading saved prompts...
                  </div>
                ) : promptPartials.length === 0 ? (
                  <div className="rounded-lg border border-gray-200 p-8 text-center text-sm text-gray-500">
                    {partialsSearchQuery
                      ? `No saved prompt partials match “${partialsSearchQuery}”.`
                      : 'No saved prompt partials yet.'}
                  </div>
                ) : (
                  <div className="space-y-2 max-h-[45vh] overflow-y-auto">
                    {promptPartials.map((partial) => {
                      const isSelected = selectedPartialId === partial.id
                      return (
                        <label
                          key={partial.id}
                          className={`block cursor-pointer rounded-lg border p-3 transition-colors ${
                            isSelected
                              ? 'border-primary-300 bg-primary-50'
                              : 'border-gray-200 hover:bg-gray-50'
                          }`}
                        >
                          <div className="flex items-start gap-3">
                            <input
                              type="radio"
                              name="call-import-prompt-partial"
                              checked={isSelected}
                              onChange={() =>
                                setSelectedPartialId(partial.id)
                              }
                              className="mt-1 h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-500"
                            />
                            <div className="min-w-0 flex-1">
                              <p className="text-sm font-semibold text-gray-900">
                                {partial.name}
                              </p>
                              {partial.description ? (
                                <p className="mt-0.5 text-xs text-gray-500">
                                  {partial.description}
                                </p>
                              ) : null}
                            </div>
                          </div>
                        </label>
                      )
                    })}
                  </div>
                )}

                {partialsImportError && (
                  <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                    {partialsImportError}
                  </div>
                )}
              </div>
              <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-2 bg-gray-50 rounded-b-lg">
                <Button
                  variant="outline"
                  onClick={closePartialsImportModal}
                  disabled={importPartialMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={() =>
                    importPartialMutation.mutate(selectedPartialId)
                  }
                  isLoading={importPartialMutation.isPending}
                  disabled={!selectedPartialId}
                >
                  Use Selected Prompt
                </Button>
              </div>
            </div>
          </div>,
        )}

      {savePartialTarget !== null &&
        renderImportDetailModal(
          (() => {
            const currentContent =
              savePartialTarget === 'standalone'
                ? transcribeDiarisationPrompt
                : evalDiarisationPrompt
            const trimmedContent = currentContent.trim()
            const canSubmit =
              savePartialMode === 'new'
                ? !!savePartialName.trim() && !!trimmedContent
                : !!savePartialExistingId && !!trimmedContent
            return (
              <div
                className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[10000]"
                onClick={closeSavePartialModal}
              >
                <div
                  className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[85vh] overflow-hidden flex flex-col"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <h3 className="text-lg font-semibold text-gray-900">
                      Save diarisation prompt to partials
                    </h3>
                    <button
                      onClick={closeSavePartialModal}
                      className="text-gray-400 hover:text-gray-600"
                      aria-label="Close save prompt partial modal"
                      disabled={savePartialMutation.isPending}
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  <div className="p-6 space-y-4 overflow-y-auto flex-1">
                    <div
                      role="tablist"
                      aria-label="Save prompt mode"
                      className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5"
                    >
                      <button
                        type="button"
                        role="tab"
                        aria-pressed={savePartialMode === 'new'}
                        onClick={() => {
                          setSavePartialMode('new')
                          setSavePartialError(null)
                        }}
                        className={`px-3 py-1 text-xs font-medium rounded-md transition ${
                          savePartialMode === 'new'
                            ? 'bg-white text-gray-900 shadow-sm ring-1 ring-inset ring-gray-200'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        Save as new
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-pressed={savePartialMode === 'existing'}
                        onClick={() => {
                          setSavePartialMode('existing')
                          setSavePartialError(null)
                        }}
                        className={`px-3 py-1 text-xs font-medium rounded-md transition ${
                          savePartialMode === 'existing'
                            ? 'bg-white text-gray-900 shadow-sm ring-1 ring-inset ring-gray-200'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        Update existing
                      </button>
                    </div>

                    {!trimmedContent && (
                      <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                        The diarisation prompt textarea is empty — there's
                        nothing to save yet.
                      </div>
                    )}

                    {savePartialMode === 'new' ? (
                      <div className="space-y-3">
                        <div>
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            Name
                            <span
                              className="ml-1 text-red-600"
                              aria-label="required"
                            >
                              *
                            </span>
                          </label>
                          <input
                            type="text"
                            value={savePartialName}
                            onChange={(e) =>
                              setSavePartialName(e.target.value)
                            }
                            placeholder="e.g. Hindi support — Gemini diarisation"
                            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            Description
                          </label>
                          <textarea
                            value={savePartialDescription}
                            onChange={(e) =>
                              setSavePartialDescription(e.target.value)
                            }
                            rows={2}
                            placeholder="Optional: short context for teammates browsing the library."
                            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                          />
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        <p className="text-xs text-gray-500">
                          Pick the saved Prompt Partial to overwrite. A new
                          version row is appended — previous versions stay
                          in the partial's history and can be reverted to.
                        </p>
                        <input
                          type="text"
                          value={partialsSearchInput}
                          onChange={(e) =>
                            setPartialsSearchInput(e.target.value)
                          }
                          placeholder="Search saved prompts..."
                          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                        />

                        {isLoadingPartials ? (
                          <div className="flex items-center justify-center py-8 text-sm text-gray-500">
                            <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                            Loading saved prompts...
                          </div>
                        ) : promptPartials.length === 0 ? (
                          <div className="rounded-lg border border-gray-200 p-8 text-center text-sm text-gray-500">
                            {partialsSearchQuery
                              ? `No saved prompt partials match “${partialsSearchQuery}”.`
                              : 'No saved prompt partials yet. Switch to "Save as new" to create one.'}
                          </div>
                        ) : (
                          <div className="space-y-2 max-h-[35vh] overflow-y-auto">
                            {promptPartials.map((partial) => {
                              const isSelected =
                                savePartialExistingId === partial.id
                              return (
                                <label
                                  key={partial.id}
                                  className={`block cursor-pointer rounded-lg border p-3 transition-colors ${
                                    isSelected
                                      ? 'border-primary-300 bg-primary-50'
                                      : 'border-gray-200 hover:bg-gray-50'
                                  }`}
                                >
                                  <div className="flex items-start gap-3">
                                    <input
                                      type="radio"
                                      name="call-import-save-partial"
                                      checked={isSelected}
                                      onChange={() =>
                                        setSavePartialExistingId(partial.id)
                                      }
                                      className="mt-1 h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-500"
                                    />
                                    <div className="min-w-0 flex-1">
                                      <p className="text-sm font-semibold text-gray-900">
                                        {partial.name}
                                      </p>
                                      {partial.description ? (
                                        <p className="mt-0.5 text-xs text-gray-500">
                                          {partial.description}
                                        </p>
                                      ) : null}
                                    </div>
                                  </div>
                                </label>
                              )
                            })}
                          </div>
                        )}
                        <div>
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            Change summary
                          </label>
                          <input
                            type="text"
                            value={savePartialChangeSummary}
                            onChange={(e) =>
                              setSavePartialChangeSummary(e.target.value)
                            }
                            placeholder="Optional: what changed in this version?"
                            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                          />
                        </div>
                      </div>
                    )}

                    <details className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs">
                      <summary className="cursor-pointer font-medium text-gray-700">
                        Preview prompt content
                        <span className="ml-1 font-normal text-gray-500">
                          ({trimmedContent.length} chars)
                        </span>
                      </summary>
                      <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded border border-gray-200 bg-white p-2 font-mono text-[11px] text-gray-800">
                        {trimmedContent || '(empty)'}
                      </pre>
                    </details>

                    {savePartialError && (
                      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                        {savePartialError}
                      </div>
                    )}
                    {savePartialSuccess && (
                      <div className="rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-800">
                        {savePartialSuccess}
                      </div>
                    )}
                  </div>
                  <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-2 bg-gray-50 rounded-b-lg">
                    <Button
                      variant="outline"
                      onClick={closeSavePartialModal}
                      disabled={savePartialMutation.isPending}
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      onClick={() =>
                        savePartialMutation.mutate({
                          content: trimmedContent,
                          mode: savePartialMode,
                          name: savePartialName.trim(),
                          description: savePartialDescription.trim(),
                          partialId: savePartialExistingId,
                          changeSummary: savePartialChangeSummary.trim(),
                        })
                      }
                      isLoading={savePartialMutation.isPending}
                      disabled={!canSubmit}
                    >
                      {savePartialMode === 'new'
                        ? 'Create Partial'
                        : 'Save New Version'}
                    </Button>
                  </div>
                </div>
              </div>
            )
          })(),
        )}

      {showTranscribeModal &&
        renderImportDetailModal(
          (() => {
            const targets = transcribeTargetRows ?? []
            const headerLabel = bulkSelectionFilter
              ? `Transcribe ${selectedCount} rows (matching filters)`
              : targets.length === 1
                ? `Transcribe row #${(targets[0]?.row_index ?? 0) + 1}`
                : `Transcribe ${targets.length} rows`
            // The STT picker is only required in the legacy two-stage
            // path; the new ``llm_only`` path skips STT entirely so we
            // drop the STT-validity check from ``canSubmit`` when that
            // mode is active. The diariser LLM picker is required in
            // both modes (it's the model that produces the turns).
            const canSubmit =
              (transcribeMode === 'llm_only'
                ? true
                : !!transcribeSTT.provider && !!transcribeSTT.model) &&
              isLLMSelectionComplete(transcribeDiariserLLM, aiProviders) &&
              (bulkSelectionFilter !== null || targets.length > 0) &&
              !transcribeRowsMutation.isPending
            return (
              <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
                <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] flex flex-col">
                  <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <h3 className="text-lg font-semibold">{headerLabel}</h3>
                    <button
                      onClick={() => {
                        if (transcribeRowsMutation.isPending) return
                        setShowTranscribeModal(false)
                        setTranscribeTargetRows(null)
                      }}
                      className="text-gray-400 hover:text-gray-600"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  <div className="p-6 space-y-4 overflow-y-auto">
                    {/* Mode toggle: STT+LLM vs LLM only. Rendered as a
                        segmented control so the active path is
                        unambiguous at a glance and the user can flip
                        between the two without scrolling. */}
                    <div className="space-y-2">
                      <p className="text-xs uppercase tracking-wide text-gray-500 font-semibold">
                        Diarisation mode
                      </p>
                      {/* Order intentionally puts LLM-only on the LEFT
                          (the recommended default) and STT+LLM on the
                          RIGHT, badged as "Advanced". This matches the
                          product direction: audio-in multimodal is the
                          first-class path and the two-stage STT pipeline
                          is the escape hatch for orgs that need a
                          specific STT contract or transcript artefact. */}
                      <div
                        role="tablist"
                        aria-label="Diarisation mode"
                        className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5"
                      >
                        <button
                          type="button"
                          role="tab"
                          aria-pressed={transcribeMode === 'llm_only'}
                          onClick={() => setTranscribeMode('llm_only')}
                          className={`px-3 py-1.5 text-xs font-medium rounded-md transition ${
                            transcribeMode === 'llm_only'
                              ? 'bg-white text-gray-900 shadow-sm'
                              : 'text-gray-600 hover:text-gray-900'
                          }`}
                        >
                          LLM only (audio in)
                        </button>
                        <button
                          type="button"
                          role="tab"
                          aria-pressed={transcribeMode === 'stt_llm'}
                          onClick={() => setTranscribeMode('stt_llm')}
                          className={`px-3 py-1.5 text-xs font-medium rounded-md transition inline-flex items-center gap-1.5 ${
                            transcribeMode === 'stt_llm'
                              ? 'bg-white text-gray-900 shadow-sm'
                              : 'text-gray-600 hover:text-gray-900'
                          }`}
                        >
                          STT + LLM diariser
                          <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-gray-600">
                            Advanced
                          </span>
                        </button>
                      </div>
                      <p className="text-[11px] text-gray-500">
                        {transcribeMode === 'llm_only'
                          ? 'Recommended. Single-stage pipeline: the audio is fed directly to a multimodal LLM along with your prompt; the model both transcribes and diarises in one call. Pick a model that accepts audio input (e.g. Gemini 1.5/2.0, GPT-4o audio-preview). Recordings longer than about 8 minutes depend on the model’s output token limit—if diarisation fails or looks cut off, switch to STT + LLM diariser.'
                          : 'Advanced fallback. Two-stage pipeline: STT transcribes the audio, then an LLM splits it into agent / user turns using your prompt. Use this when you need a specific STT contract, longer recordings, or to reuse an existing transcript artefact.'}
                      </p>
                    </div>
                    {transcribeMode === 'stt_llm' && (
                      <div className="space-y-2">
                        <p className="text-xs uppercase tracking-wide text-gray-500 font-semibold">
                          1. Speech-to-text
                        </p>
                        <p className="text-sm text-gray-600">
                          The STT step produces plain text only; the LLM
                          below splits it into agent / user turns.
                        </p>
                        <ProviderModelPicker
                          kind="stt"
                          value={transcribeSTT}
                          onChange={setTranscribeSTT}
                          providerAllowList={STT_PROVIDER_ALLOWLIST}
                          defaultLabel="Pick an STT provider"
                          allowCredentialPick
                        />
                        <input
                          type="text"
                          value={transcribeLanguage}
                          onChange={(e) =>
                            setTranscribeLanguage(e.target.value)
                          }
                          placeholder="Language hint (e.g. en, hi)"
                          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                        />
                      </div>
                    )}
                    <div className="space-y-2 pt-1 border-t border-gray-100">
                      <p className="text-xs uppercase tracking-wide text-gray-500 font-semibold pt-3">
                        {transcribeMode === 'stt_llm'
                          ? '2. LLM diariser'
                          : 'Multimodal diariser LLM'}
                      </p>
                      <p className="text-sm text-gray-600">
                        {transcribeMode === 'stt_llm' ? (
                          <>
                            Pick a chat model and tweak the prompt below.
                            The model receives the STT plain text and the
                            prompt and must return a JSON array of{' '}
                            <code className="px-1 bg-gray-100 rounded text-[11px]">
                              {'{ speaker, text }'}
                            </code>{' '}
                            turns.
                          </>
                        ) : (
                          <>
                            Pick a chat model that accepts audio input
                            (e.g. <code className="px-1 bg-gray-100 rounded text-[11px]">gemini-2.5-flash</code>,{' '}
                            <code className="px-1 bg-gray-100 rounded text-[11px]">gpt-4o-audio-preview</code>).
                            The model receives the recording bytes and
                            the prompt and must return a JSON array of{' '}
                            <code className="px-1 bg-gray-100 rounded text-[11px]">
                              {'{ speaker, text }'}
                            </code>{' '}
                            turns.
                          </>
                        )}
                      </p>
                      <ProviderModelPicker
                        kind="llm"
                        value={transcribeDiariserLLM}
                        onChange={setTranscribeDiariserLLM}
                        defaultLabel="Pick an LLM for diarisation"
                        allowCredentialPick
                        audioCapableOnly={transcribeMode === 'llm_only'}
                      />
                      <div className="flex items-center justify-between pt-1">
                        <label className="text-xs font-medium text-gray-700">
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
                              setPartialsImportTarget('standalone')
                            }}
                            className="text-[11px] text-primary-600 hover:text-primary-700"
                          >
                            Import from saved partials
                          </button>
                          <button
                            type="button"
                            onClick={() => openSavePartialModal('standalone')}
                            disabled={!transcribeDiarisationPrompt.trim()}
                            title={
                              transcribeDiarisationPrompt.trim()
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
                                setTranscribeDiarisationPrompt(
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
                        value={transcribeDiarisationPrompt}
                        onChange={(e) =>
                          setTranscribeDiarisationPrompt(e.target.value)
                        }
                        rows={10}
                        placeholder={
                          defaultDiarisationPrompt ||
                          'Describe how the LLM should split the transcript into agent / user turns…'
                        }
                        className="w-full px-3 py-2 text-xs font-mono border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                      />
                      <p className="text-[11px] text-gray-500">
                        Leave blank to fall back to the canonical default
                        prompt the worker ships with.
                      </p>
                    </div>
                    <label className="flex items-start gap-2 text-xs pt-2 border-t border-gray-100">
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={transcribeOverwriteStandalone}
                        onChange={(e) =>
                          setTranscribeOverwriteStandalone(e.target.checked)
                        }
                      />
                      <span>
                        Overwrite existing transcripts (otherwise rows
                        with a transcript are skipped).
                      </span>
                    </label>
                    {transcribeError && (
                      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                        {transcribeError}
                      </div>
                    )}
                  </div>
                  <div className="px-6 py-4 border-t border-gray-200 flex gap-2 bg-gray-50 rounded-b-lg">
                    <Button
                      variant="outline"
                      onClick={() => {
                        if (transcribeRowsMutation.isPending) return
                        setShowTranscribeModal(false)
                        setTranscribeTargetRows(null)
                      }}
                      disabled={transcribeRowsMutation.isPending}
                      className="flex-1"
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      isLoading={transcribeRowsMutation.isPending}
                      disabled={!canSubmit}
                      onClick={() =>
                        transcribeRowsMutation.mutate({
                          rowIds: bulkSelectionFilter
                            ? null
                            : targets.map((r) => r.id),
                          mode: transcribeMode,
                          stt: transcribeSTT,
                          diariserLLM: transcribeDiariserLLM,
                          diarisationPrompt: transcribeDiarisationPrompt,
                          language: transcribeLanguage,
                          overwrite: transcribeOverwriteStandalone,
                        })
                      }
                      className="flex-1"
                    >
                      Start
                    </Button>
                  </div>
                </div>
              </div>
            )
          })(),
        )}

      {showBulkActionsModal &&
        selectedCount > 0 &&
        renderImportDetailModal(
          <div
            className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50"
            onClick={() => {
              if (bulkCancelDiarisationMutation.isPending) return
              setShowBulkActionsModal(false)
              setBulkActionError(null)
              setBulkActionResult(null)
            }}
          >
            <div
              className="bg-white rounded-lg shadow-xl max-w-xl w-full mx-4 max-h-[85vh] overflow-hidden flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-start gap-3">
                <div className="min-w-0">
                  <h3 className="text-lg font-semibold text-gray-900">
                    Bulk actions
                  </h3>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {selectedCount} row{selectedCount === 1 ? '' : 's'}{' '}
                    selected
                    {selectionSpansPages
                      ? ' · selection spans pages (per-action counts below are for on-page rows only; the backend filters the rest)'
                      : ''}
                    .
                  </p>
                </div>
                <button
                  onClick={() => {
                    if (bulkCancelDiarisationMutation.isPending) return
                    setShowBulkActionsModal(false)
                    setBulkActionError(null)
                    setBulkActionResult(null)
                  }}
                  className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                  aria-label="Close bulk actions modal"
                  disabled={bulkCancelDiarisationMutation.isPending}
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="p-5 space-y-3 overflow-y-auto flex-1">
                {/*
                  Action card 1 — Diarise / re-diarise.

                  ``transcribeReadySelection`` counts on-page rows that
                  have a recording AND aren't already in-flight. With
                  cross-page selections we hand off the full
                  ``selectedRowIds`` set and rely on the worker's
                  server-side filter to skip rows that don't qualify.
                 */}
                <div className="rounded-lg border border-gray-200 p-4 hover:border-purple-300 hover:bg-purple-50/40 transition-colors">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-purple-100 text-purple-700 flex items-center justify-center">
                      <Mic className="h-5 w-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-semibold text-gray-900">
                        Diarise / re-diarise
                      </h4>
                      <p className="text-xs text-gray-600 mt-1">
                        {selectionSpansPages
                          ? `Run diarisation on the ${selectedCount} selected rows. Rows without a recording or already in flight are skipped server-side.`
                          : transcribeReadySelection.length === 0
                          ? 'No rows in this selection are ready to diarise (each is either missing a recording or already in flight).'
                          : `${transcribeReadySelection.length} of ${selectedCount} selected row${
                              selectedCount === 1 ? '' : 's'
                            } can be diarised right now. The rest will be skipped.`}
                      </p>
                    </div>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={
                        !bulkSelectionFilter &&
                        !selectionSpansPages &&
                        transcribeReadySelection.length === 0
                      }
                      onClick={() => {
                        setShowBulkActionsModal(false)
                        setBulkActionError(null)
                        setBulkActionResult(null)
                        if (bulkSelectionFilter) {
                          openTranscribeModal([])
                        } else if (selectionSpansPages) {
                          // Cross-page selection: forward synthetic
                          // rows (id-only) so the modal targets the
                          // batch endpoint without inventing fake
                          // row_index values for the header label.
                          openTranscribeModal(
                            Array.from(selectedRowIds).map(
                              (rowId) =>
                                ({
                                  id: rowId,
                                  row_index: 0,
                                } as unknown as CallImportRow),
                            ),
                          )
                        } else {
                          openTranscribeModal(transcribeReadySelection)
                        }
                      }}
                      className="flex-shrink-0"
                    >
                      Diarise
                    </Button>
                  </div>
                </div>

                {/*
                  Action card 2 — Stop diarisation.

                  The button is disabled when there's nothing in flight
                  on the visible page; for cross-page selections we
                  allow the click and let the server's
                  ``cancelled / skipped`` summary do the talking.
                 */}
                <div className="rounded-lg border border-gray-200 p-4 hover:border-amber-300 hover:bg-amber-50/40 transition-colors">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center">
                      <Square className="h-5 w-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-semibold text-gray-900">
                        Stop diarisation
                      </h4>
                      <p className="text-xs text-gray-600 mt-1">
                        {selectionSpansPages
                          ? `Revoke any in-flight or queued diarisation across the ${selectedCount} selected rows. Rows that finished already are skipped.`
                          : cancellableSelection.length === 0
                          ? 'No rows in this selection are currently queued or running. Nothing to stop.'
                          : `Stop diarisation for ${cancellableSelection.length} pending / running row${
                              cancellableSelection.length === 1 ? '' : 's'
                            }. Each row is flipped to "failed" with a "Cancelled by user" message.`}
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      isLoading={bulkCancelDiarisationMutation.isPending}
                      disabled={
                        bulkCancelDiarisationMutation.isPending ||
                        (!selectionSpansPages &&
                          cancellableSelection.length === 0)
                      }
                      onClick={() => {
                        if (bulkCancelDiarisationMutation.isPending) return
                        // For on-page selections we narrow to the
                        // cancellable subset so the server doesn't
                        // need to discover skips; for cross-page we
                        // send everything and let the server filter.
                        if (bulkSelectionFilter) {
                          bulkCancelDiarisationMutation.mutate({
                            rowFilter: bulkSelectionFilter,
                          })
                          return
                        }
                        const ids = selectionSpansPages
                          ? Array.from(selectedRowIds)
                          : cancellableSelection.map((r) => r.id)
                        if (ids.length === 0) return
                        bulkCancelDiarisationMutation.mutate({ rowIds: ids })
                      }}
                      className="flex-shrink-0 text-amber-700 border-amber-300 hover:bg-amber-50"
                    >
                      Stop
                    </Button>
                  </div>
                </div>

                {/*
                  Action card 3 — Delete rows.

                  We close THIS modal and hand off to the existing
                  ConfirmModal so the destructive flow keeps its
                  "type-aware confirm" behaviour. No duplication of
                  the irreversible-action copy here.
                 */}
                <div className="rounded-lg border border-gray-200 p-4 hover:border-red-300 hover:bg-red-50/40 transition-colors">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-red-100 text-red-700 flex items-center justify-center">
                      <Trash2 className="h-5 w-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-semibold text-gray-900">
                        Delete rows
                      </h4>
                      <p className="text-xs text-gray-600 mt-1">
                        Permanently remove {selectedCount} selected row
                        {selectedCount === 1 ? '' : 's'} from this import,
                        along with their recordings. In-flight
                        tasks for these rows will be revoked. This cannot
                        be undone.
                      </p>
                    </div>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => {
                        setShowBulkActionsModal(false)
                        setBulkActionError(null)
                        setBulkActionResult(null)
                        setBulkDeleteRowsError(null)
                        setShowBulkDeleteRows(true)
                      }}
                      className="flex-shrink-0"
                    >
                      Delete
                    </Button>
                  </div>
                </div>

                {bulkActionResult && (
                  <div className="rounded-md border border-green-200 bg-green-50 p-3 text-xs text-green-800 flex items-start gap-2">
                    <Check className="h-4 w-4 text-green-600 flex-shrink-0 mt-0.5" />
                    <div className="min-w-0 flex-1">{bulkActionResult}</div>
                    <button
                      type="button"
                      onClick={() => setBulkActionResult(null)}
                      className="text-green-700 hover:text-green-900 flex-shrink-0"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}

                {bulkActionError && (
                  <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-800 flex items-start gap-2">
                    <AlertCircle className="h-4 w-4 text-red-600 flex-shrink-0 mt-0.5" />
                    <div className="min-w-0 flex-1">{bulkActionError}</div>
                    <button
                      type="button"
                      onClick={() => setBulkActionError(null)}
                      className="text-red-700 hover:text-red-900 flex-shrink-0"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </div>

              <div className="px-6 py-3 border-t border-gray-200 bg-gray-50 flex justify-end">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={bulkCancelDiarisationMutation.isPending}
                  onClick={() => {
                    if (bulkCancelDiarisationMutation.isPending) return
                    setShowBulkActionsModal(false)
                    setBulkActionError(null)
                    setBulkActionResult(null)
                  }}
                >
                  Close
                </Button>
              </div>
            </div>
          </div>,
        )}
    </>
  )
}
