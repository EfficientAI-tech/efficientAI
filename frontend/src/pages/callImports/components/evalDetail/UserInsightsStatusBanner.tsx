import { useEffect, useState } from 'react'
import type { EvaluationUserInsightsState } from '../../../../types/api'
import AIProviderModelPicker from '../../../../components/AIProviderModelPicker'
import Button from '../../../../components/Button'
import { apiClient } from '../../../../lib/api'
import { EvaluationBackgroundJobCard } from './EvaluationBackgroundJobCard'
import { getUserInsightsJobProgress } from './evaluationJobProgress'
import { UserInsightsTranscriptSourceSelect } from './UserInsightsTranscriptSourceSelect'

function UserInsightsResumePanel({
  state,
  tone,
  title,
  message,
  resuming,
  onResume,
}: {
  state: EvaluationUserInsightsState
  tone: 'neutral' | 'error'
  title: string
  message: string
  resuming: boolean
  onResume: (options: {
    provider: string
    model: string
    transcript_source: 'diarised' | 'production'
  }) => void
}) {
  const [pickerProvider, setPickerProvider] = useState(state.provider ?? '')
  const [pickerModel, setPickerModel] = useState(state.model ?? '')
  const [transcriptSource, setTranscriptSource] = useState<'diarised' | 'production'>(
    state.transcript_source === 'production' ? 'production' : 'diarised',
  )

  useEffect(() => {
    if (state.provider) setPickerProvider(state.provider)
    if (state.model) setPickerModel(state.model)
    if (state.transcript_source === 'production' || state.transcript_source === 'diarised') {
      setTranscriptSource(state.transcript_source)
    }
  }, [state.provider, state.model, state.transcript_source])

  const canResume = Boolean(pickerProvider.trim() && pickerModel.trim())

  const borderClass =
    tone === 'error' ? 'border-red-200 bg-red-50/50' : 'border-gray-200 bg-gray-50/80'
  const messageClass = tone === 'error' ? 'text-red-700' : 'text-gray-600'

  return (
    <section className={`rounded-lg border px-3 py-2.5 ${borderClass}`}>
      <p className="text-xs font-semibold text-gray-900">{title}</p>
      <p className={`text-[11px] mt-1 ${messageClass}`}>{message}</p>
      {state.progress ? (
        <p className="text-[10px] text-gray-500 mt-1">
          Saved progress: batch {state.progress.completed_batches ?? 0} /{' '}
          {state.progress.total_batches ?? 0}
          {state.progress.completed_rows != null && state.progress.total_rows != null
            ? ` · ${state.progress.completed_rows.toLocaleString()} / ${state.progress.total_rows.toLocaleString()} calls`
            : null}
        </p>
      ) : null}
      <div className="mt-3 space-y-2 rounded-md border border-gray-100 bg-white/90 p-2.5">
        <p className="text-[10px] font-medium text-gray-800">Model for resume</p>
        <p className="text-[10px] text-gray-500 leading-snug">
          Checkpoints are kept. Pick the provider and model for the remaining extraction
          passes (defaults to the last run).
        </p>
        <AIProviderModelPicker
          provider={pickerProvider}
          model={pickerModel}
          onProviderChange={setPickerProvider}
          onModelChange={setPickerModel}
          disabled={resuming}
          size="sm"
        />
        <UserInsightsTranscriptSourceSelect
          value={transcriptSource}
          onChange={setTranscriptSource}
          disabled={resuming}
        />
      </div>
      <div className="mt-2 flex justify-end">
        <Button
          size="sm"
          variant="primary"
          onClick={() =>
            onResume({
              provider: pickerProvider.trim(),
              model: pickerModel.trim(),
              transcript_source: transcriptSource,
            })
          }
          isLoading={resuming}
          disabled={resuming || !canResume}
        >
          Resume
        </Button>
      </div>
    </section>
  )
}

function UserInsightsStatusBanner({
  state,
  isLoading,
  callImportId,
  evaluationId,
  onRefresh,
  onStateChange,
}: {
  state: EvaluationUserInsightsState | null
  isLoading: boolean
  callImportId: string
  evaluationId: string
  onRefresh?: () => void
  onStateChange?: (state: EvaluationUserInsightsState) => void
}) {
  const [cancelling, setCancelling] = useState(false)
  const [resuming, setResuming] = useState(false)

  if (isLoading) {
    return (
      <section className="rounded-lg border border-gray-200 bg-white px-3 py-2.5">
        <p className="text-xs text-gray-500">Loading user insights…</p>
      </section>
    )
  }

  if (!state || state.status === 'idle' || state.status === 'completed') {
    return null
  }

  const handleCancel = async () => {
    setCancelling(true)
    try {
      const updated = await apiClient.callImports.cancelCallImportEvaluationUserInsights(
        callImportId,
        evaluationId,
      )
      onStateChange?.(updated)
      onRefresh?.()
    } finally {
      setCancelling(false)
    }
  }

  const handleResume = async (options: {
    provider: string
    model: string
    transcript_source: 'diarised' | 'production'
  }) => {
    setResuming(true)
    try {
      await apiClient.callImports.generateCallImportEvaluationUserInsights(
        callImportId,
        evaluationId,
        {
          resume: true,
          provider: options.provider,
          model: options.model,
          transcript_source: options.transcript_source,
        },
      )
      onRefresh?.()
    } finally {
      setResuming(false)
    }
  }

  if (state.status === 'running') {
    const progressView = getUserInsightsJobProgress(state)
    const modelMeta =
      state.provider || state.model
        ? `Model: ${[state.provider, state.model].filter(Boolean).join(' · ')}`
        : null
    return (
      <EvaluationBackgroundJobCard
        title="AI user insights"
        progress={{
          ...progressView,
          metaLine: progressView.metaLine || modelMeta,
          phaseLabel: state.heartbeat_stale
            ? 'No worker has updated this job for a while. Resume picks up from the saved checkpoints.'
            : progressView.phaseLabel,
        }}
        onStop={handleCancel}
        stopLoading={cancelling}
        onResume={
          state.heartbeat_stale
            ? () =>
              handleResume({
                provider: state.provider ?? '',
                model: state.model ?? '',
                transcript_source: state.transcript_source ?? 'diarised',
              })
            : undefined
        }
        resumeLoading={resuming}
      />
    )
  }

  if (state.status === 'cancelled') {
    return (
      <UserInsightsResumePanel
        state={state}
        tone="neutral"
        title="User insights stopped"
        message={
          state.error_message ||
          'Generation was cancelled. Progress was saved; choose a model and resume.'
        }
        resuming={resuming}
        onResume={handleResume}
      />
    )
  }

  return (
    <UserInsightsResumePanel
      state={state}
      tone="error"
      title="User insights failed"
      message={state.error_message || 'User insights generation failed.'}
      resuming={resuming}
      onResume={handleResume}
    />
  )
}

export { UserInsightsStatusBanner }
