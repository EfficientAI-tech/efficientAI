import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Brain, MessageSquare, Volume2, X, SlidersHorizontal } from 'lucide-react'
import { apiClient } from '../../../lib/api'
import {
  ModelProvider,
  VoiceBundle,
  VoiceBundleType,
  type VoiceBundleUpdate,
} from '../../../types/api'
import { getProviderLabel, getProviderLogo } from '../../../config/providers'
import LLMAdvancedOptionsPanel from '../../../components/providers/LLMAdvancedOptionsPanel'
import {
  isLLMGenerationConfigEmpty,
  normalizeLLMConfig,
  summarizeLLMConfig,
  type LLMGenerationConfig,
} from '../../../config/llmGenerationParams'
import Button from '../../../components/Button'
import ParamSlider from './ParamSlider'

type ModelOptionsCache = Record<
  string,
  {
    stt: string[]
    llm: string[]
    tts: string[]
    tts_voices: Record<string, { id: string; name: string; gender?: string }[]>
    tts_sample_rates: number[]
  }
>

function bundleToLlmConfig(bundle: VoiceBundle): LLMGenerationConfig | null {
  const config: LLMGenerationConfig = { ...(bundle.llm_config || {}) }
  if (config.temperature == null && bundle.llm_temperature != null) {
    config.temperature = bundle.llm_temperature
  }
  if (config.max_tokens == null && bundle.llm_max_tokens != null) {
    config.max_tokens = bundle.llm_max_tokens
  }
  return isLLMGenerationConfigEmpty(config) ? null : normalizeLLMConfig(config)
}

interface DraftParams {
  stt_model: string
  llm_model: string
  llm_config: LLMGenerationConfig | null
  tts_voice: string
  tts_config: Record<string, unknown>
}

function draftFromBundle(bundle: VoiceBundle): DraftParams {
  return {
    stt_model: bundle.stt_model || '',
    llm_model: bundle.llm_model || '',
    llm_config: bundleToLlmConfig(bundle),
    tts_voice: bundle.tts_voice || '',
    tts_config: { ...(bundle.tts_config || {}) },
  }
}

interface VoiceBundleParamsModalProps {
  bundle: VoiceBundle
  showToast: (message: string, type: 'success' | 'error') => void
  disabled?: boolean
  /** Show full STT/LLM/TTS editor inline on Configuration (no summary + open button). */
  expanded?: boolean
}

export default function VoiceBundleParamsModal({
  bundle,
  showToast,
  disabled = false,
  expanded = false,
}: VoiceBundleParamsModalProps) {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<DraftParams>(() => draftFromBundle(bundle))

  useEffect(() => {
    setDraft(draftFromBundle(bundle))
  }, [bundle.id, bundle.updated_at])

  useEffect(() => {
    if (open) {
      setDraft(draftFromBundle(bundle))
    }
  }, [open, bundle])

  const { data: modelConfigs = {} } = useQuery<ModelOptionsCache>({
    queryKey: ['model-configs'],
    queryFn: async () => {
      const providers = Object.values(ModelProvider)
      const configs: ModelOptionsCache = {}
      for (const provider of providers) {
        try {
          const options = await apiClient.getModelOptions(provider)
          configs[provider] = {
            stt: options.stt || [],
            llm: options.llm || [],
            tts: options.tts || [],
            tts_voices: options.tts_voices || {},
            tts_sample_rates: options.tts_sample_rates || [],
          }
        } catch {
          configs[provider] = {
            stt: [],
            llm: [],
            tts: [],
            tts_voices: {},
            tts_sample_rates: [],
          }
        }
      }
      return configs
    },
    staleTime: 5 * 60 * 1000,
    enabled: open || expanded,
  })

  const optionsFor = (provider?: ModelProvider | null) =>
    provider ? modelConfigs[provider] : undefined

  const sttOptions = optionsFor(bundle.stt_provider)
  const llmOptions = optionsFor(bundle.llm_provider)
  const ttsOptions = optionsFor(bundle.tts_provider)

  const ttsVoices =
    bundle.tts_provider && bundle.tts_model
      ? ttsOptions?.tts_voices?.[bundle.tts_model] || []
      : []

  const llmSummary = summarizeLLMConfig(bundleToLlmConfig(bundle))

  const isDirty = useMemo(() => {
    const initial = draftFromBundle(bundle)
    return JSON.stringify(initial) !== JSON.stringify(draft)
  }, [bundle, draft])

  const saveMutation = useMutation({
    mutationFn: (payload: VoiceBundleUpdate) => apiClient.updateVoiceBundle(bundle.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['voicebundles'] })
      queryClient.invalidateQueries({ queryKey: ['agent'] })
      showToast('Voice bundle parameters saved', 'success')
      if (!expanded) {
        setOpen(false)
      }
    },
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
      showToast(error.response?.data?.detail || error.message || 'Failed to save bundle', 'error')
    },
  })

  const handleSave = () => {
    saveMutation.mutate({
      llm_model: draft.llm_model || undefined,
      llm_config: draft.llm_config || undefined,
      llm_temperature: null,
      llm_max_tokens: null,
      stt_model: draft.stt_model || undefined,
      tts_voice: draft.tts_voice || null,
      tts_config: draft.tts_config,
    })
  }

  const updateLlmConfig = (patch: Partial<LLMGenerationConfig>) => {
    setDraft((prev) => {
      const merged = normalizeLLMConfig({ ...(prev.llm_config || {}), ...patch })
      return {
        ...prev,
        llm_config: isLLMGenerationConfigEmpty(merged) ? null : merged,
      }
    })
  }

  const closeModal = () => {
    if (saveMutation.isPending) return
    setOpen(false)
    setDraft(draftFromBundle(bundle))
  }

  const renderPortal = (content: ReactNode) => {
    if (typeof document === 'undefined') return null
    return createPortal(content, document.body)
  }

  if (bundle.bundle_type === VoiceBundleType.S2S) {
    return (
      <p className="text-sm text-gray-500">
        Speech-to-speech bundle — use Voice Bundles to adjust the S2S model.
      </p>
    )
  }

  const pipelineEditorBody = (idPrefix: string) => (
    <div className="space-y-5">
      <section className="rounded-lg border border-blue-100 bg-blue-50/50 p-4 space-y-4">
        <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-blue-600" />
          Speech-to-text (STT)
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Provider</label>
            <div className="flex items-center gap-2 text-sm text-gray-800 bg-white border border-gray-200 rounded-lg px-3 py-2">
              {bundle.stt_provider && getProviderLogo(bundle.stt_provider) ? (
                <img src={getProviderLogo(bundle.stt_provider)!} alt="" className="h-5 w-5 object-contain" />
              ) : null}
              {bundle.stt_provider ? getProviderLabel(bundle.stt_provider) : '—'}
            </div>
          </div>
          <div>
            <label htmlFor={`${idPrefix}-stt-model`} className="block text-xs font-medium text-gray-600 mb-1">
              Model
            </label>
            <select
              id={`${idPrefix}-stt-model`}
              disabled={disabled || !bundle.stt_provider}
              value={draft.stt_model}
              onChange={(e) => setDraft((p) => ({ ...p, stt_model: e.target.value }))}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500"
            >
              {(sttOptions?.stt || [draft.stt_model].filter(Boolean)).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-purple-100 bg-purple-50/30 p-4 space-y-4">
        <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
          <Brain className="h-4 w-4 text-purple-600" />
          Language model (LLM)
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Provider</label>
            <div className="flex items-center gap-2 text-sm text-gray-800 bg-white border border-gray-200 rounded-lg px-3 py-2">
              {bundle.llm_provider && getProviderLogo(bundle.llm_provider) ? (
                <img src={getProviderLogo(bundle.llm_provider)!} alt="" className="h-5 w-5 object-contain" />
              ) : null}
              {bundle.llm_provider ? getProviderLabel(bundle.llm_provider) : '—'}
            </div>
          </div>
          <div>
            <label htmlFor={`${idPrefix}-llm-model`} className="block text-xs font-medium text-gray-600 mb-1">
              Model
            </label>
            <select
              id={`${idPrefix}-llm-model`}
              disabled={disabled || !bundle.llm_provider}
              value={draft.llm_model}
              onChange={(e) => setDraft((p) => ({ ...p, llm_model: e.target.value }))}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500"
            >
              {(llmOptions?.llm || [draft.llm_model].filter(Boolean)).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Model parameters</p>
          <ParamSlider
            label="Temperature"
            min={0}
            max={2}
            step={0.1}
            disabled={disabled}
            value={draft.llm_config?.temperature ?? null}
            onChange={(temperature) => updateLlmConfig({ temperature })}
            helpText="Higher values increase creativity; lower values stay closer to the prompt."
          />
          <ParamSlider
            label="Max tokens (per LLM turn)"
            min={1}
            max={8192}
            step={1}
            integer
            disabled={disabled}
            value={draft.llm_config?.max_tokens ?? null}
            onChange={(max_tokens) => updateLlmConfig({ max_tokens })}
            helpText="Longer responses can increase speech latency but allow richer answers."
          />
          <LLMAdvancedOptionsPanel
            provider={bundle.llm_provider}
            value={draft.llm_config}
            onChange={(llm_config) => setDraft((p) => ({ ...p, llm_config }))}
            disabled={disabled}
            defaultExpanded={expanded}
          />
        </div>
      </section>

      <section className="rounded-lg border border-green-100 bg-green-50/50 p-4 space-y-4">
        <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
          <Volume2 className="h-4 w-4 text-green-600" />
          Text-to-speech (TTS)
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Provider</label>
            <div className="flex items-center gap-2 text-sm text-gray-800 bg-white border border-gray-200 rounded-lg px-3 py-2">
              {bundle.tts_provider && getProviderLogo(bundle.tts_provider) ? (
                <img src={getProviderLogo(bundle.tts_provider)!} alt="" className="h-5 w-5 object-contain" />
              ) : null}
              {bundle.tts_provider ? getProviderLabel(bundle.tts_provider) : '—'}
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">TTS model</label>
            <div className="text-sm text-gray-800 bg-white border border-gray-200 rounded-lg px-3 py-2">
              {bundle.tts_model || '—'}
            </div>
          </div>
          <div className="sm:col-span-2">
            <label htmlFor={`${idPrefix}-tts-voice`} className="block text-xs font-medium text-gray-600 mb-1">
              Voice
            </label>
            {ttsVoices.length > 0 ? (
              <select
                id={`${idPrefix}-tts-voice`}
                disabled={disabled}
                value={draft.tts_voice}
                onChange={(e) => setDraft((p) => ({ ...p, tts_voice: e.target.value }))}
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500"
              >
                {ttsVoices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                    {v.gender ? ` (${v.gender})` : ''}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={`${idPrefix}-tts-voice`}
                type="text"
                disabled={disabled}
                value={draft.tts_voice}
                onChange={(e) => setDraft((p) => ({ ...p, tts_voice: e.target.value }))}
                placeholder="Voice id"
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500"
              />
            )}
          </div>
          {(() => {
            const rates = ttsOptions?.tts_sample_rates || []
            if (rates.length === 0) return null
            const currentHz = Number(draft.tts_config?.sample_rate_hz ?? 8000)
            return (
              <div>
                <label htmlFor={`${idPrefix}-tts-rate`} className="block text-xs font-medium text-gray-600 mb-1">
                  Output sample rate
                </label>
                <select
                  id={`${idPrefix}-tts-rate`}
                  disabled={disabled}
                  value={currentHz}
                  onChange={(e) =>
                    setDraft((p) => ({
                      ...p,
                      tts_config: { ...p.tts_config, sample_rate_hz: Number(e.target.value) },
                    }))
                  }
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500"
                >
                  {rates.map((hz) => (
                    <option key={hz} value={hz}>
                      {hz / 1000} kHz
                    </option>
                  ))}
                </select>
              </div>
            )
          })()}
        </div>
      </section>
    </div>
  )

  const editorFooter = (showCancel: boolean) => (
    <div className="flex flex-wrap items-center justify-end gap-2 pt-4 border-t border-gray-200">
      {showCancel && (
        <Button type="button" variant="outline" size="sm" disabled={saveMutation.isPending} onClick={closeModal}>
          Cancel
        </Button>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || !isDirty || saveMutation.isPending}
        onClick={() => setDraft(draftFromBundle(bundle))}
      >
        Reset
      </Button>
      <Button
        type="button"
        variant="primary"
        size="sm"
        disabled={disabled || !isDirty || saveMutation.isPending}
        isLoading={saveMutation.isPending}
        onClick={handleSave}
      >
        Save parameters
      </Button>
    </div>
  )

  if (expanded) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80">
          <h4 className="text-sm font-semibold text-gray-900">Voice pipeline parameters</h4>
          <p className="text-xs text-gray-500 mt-0.5">{bundle.name}</p>
        </div>
        <div className="p-4 max-h-[min(70vh,720px)] overflow-y-auto">{pipelineEditorBody('inline')}</div>
        <div className="px-4 pb-4">{editorFooter(false)}</div>
      </div>
    )
  }

  return (
    <>
      <div className="space-y-3">
        <div className="grid gap-2 text-sm text-gray-700">
          <div className="flex items-center gap-2 p-2 rounded-md bg-blue-50/80">
            <MessageSquare className="h-4 w-4 text-blue-600 shrink-0" />
            <span className="truncate">STT: {bundle.stt_model || '—'}</span>
          </div>
          <div className="flex items-center gap-2 p-2 rounded-md bg-purple-50/80">
            <Brain className="h-4 w-4 text-purple-600 shrink-0" />
            <span className="truncate">
              LLM: {bundle.llm_model || '—'}
              {llmSummary ? ` · ${llmSummary}` : ''}
            </span>
          </div>
          <div className="flex items-center gap-2 p-2 rounded-md bg-green-50/80">
            <Volume2 className="h-4 w-4 text-green-600 shrink-0" />
            <span className="truncate">TTS: {bundle.tts_voice || bundle.tts_model || '—'}</span>
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => setOpen(true)}
          leftIcon={<SlidersHorizontal className="h-4 w-4" />}
          className="w-full sm:w-auto"
        >
          Tune STT, LLM & TTS
        </Button>
      </div>

      {open &&
        renderPortal(
          <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-gray-500/75">
            <div
              className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-gray-200 shrink-0">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">Voice pipeline parameters</h3>
                  <p className="text-sm text-gray-500 mt-0.5">{bundle.name}</p>
                </div>
                <button
                  type="button"
                  onClick={closeModal}
                  disabled={saveMutation.isPending}
                  className="text-gray-400 hover:text-gray-600 p-1"
                  aria-label="Close"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto px-5 py-4">{pipelineEditorBody('modal')}</div>
              <div className="px-5 pb-4 shrink-0">{editorFooter(true)}</div>
            </div>
          </div>
        )}
    </>
  )
}
