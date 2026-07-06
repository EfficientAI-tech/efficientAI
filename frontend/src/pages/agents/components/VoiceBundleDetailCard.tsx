import { Mic, MessageSquare, Brain, Volume2, Edit, ExternalLink } from 'lucide-react'
import { VoiceBundle, VoiceBundleType, ModelProvider } from '../../../types/api'
import { getProviderLabel, getProviderLogo } from '../../../config/providers'
import { summarizeLLMConfig, type LLMGenerationConfig } from '../../../config/llmGenerationParams'
import Button from '../../../components/Button'

function bundleLLMConfig(bundle: VoiceBundle): LLMGenerationConfig {
  return {
    temperature: bundle.llm_temperature ?? undefined,
    max_tokens: bundle.llm_max_tokens ?? undefined,
    ...(bundle.llm_config || {}),
  }
}

interface VoiceBundleDetailCardProps {
  bundle: VoiceBundle | null | undefined
  onEdit?: () => void
  onManageInVoiceBundles?: () => void
}

function ProviderRow({
  provider,
  model,
  extra,
}: {
  provider?: string | null
  model?: string | null
  extra?: string | null
}) {
  if (!provider || !model) {
    return <span className="text-gray-500">Not configured</span>
  }
  const mp = provider as ModelProvider
  const logo = getProviderLogo(mp)
  return (
    <div className="flex items-center gap-2 flex-wrap text-sm text-gray-700">
      {logo ? <img src={logo} alt={getProviderLabel(mp)} className="w-4 h-4 object-contain" /> : null}
      <span className="font-medium">{getProviderLabel(mp)}</span>
      <span className="text-gray-400">·</span>
      <span>{model}</span>
      {extra ? (
        <>
          <span className="text-gray-400">·</span>
          <span>{extra}</span>
        </>
      ) : null}
    </div>
  )
}

export default function VoiceBundleDetailCard({
  bundle,
  onEdit,
  onManageInVoiceBundles,
}: VoiceBundleDetailCardProps) {
  if (!bundle) {
    return (
      <div className="border border-dashed border-gray-300 rounded-lg p-8 text-center bg-gray-50">
        <Mic className="h-10 w-10 text-gray-300 mx-auto mb-3" />
        <p className="text-sm text-gray-500">No voice bundle configured for this test agent.</p>
        <p className="text-xs text-gray-400 mt-1">Assign a bundle in edit mode to enable test calls.</p>
      </div>
    )
  }

  const llmSummary = summarizeLLMConfig(bundleLLMConfig(bundle))

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden bg-white">
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 bg-gray-50">
        <div>
          <h3 className="text-base font-semibold text-gray-900">{bundle.name}</h3>
          {bundle.description && <p className="text-sm text-gray-500 mt-0.5">{bundle.description}</p>}
          <p className="text-xs text-gray-400 mt-1 capitalize">
            {bundle.bundle_type === VoiceBundleType.S2S ? 'Speech-to-Speech' : 'STT + LLM + TTS'}
            {!bundle.is_active && ' · Inactive'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {onEdit && (
            <Button type="button" variant="outline" size="sm" onClick={onEdit} leftIcon={<Edit className="h-4 w-4" />}>
              Edit
            </Button>
          )}
          {onManageInVoiceBundles && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onManageInVoiceBundles}
              leftIcon={<ExternalLink className="h-4 w-4" />}
            >
              Voice Bundles
            </Button>
          )}
        </div>
      </div>

      <div className="p-5 space-y-3">
        {bundle.bundle_type === VoiceBundleType.S2S ? (
          <div className="p-3 bg-orange-50 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <Mic className="h-4 w-4 text-orange-600" />
              <span className="text-xs font-semibold text-orange-900 uppercase">Speech-to-Speech</span>
            </div>
            <ProviderRow provider={bundle.s2s_provider} model={bundle.s2s_model} />
          </div>
        ) : (
          <>
            <div className="p-3 bg-blue-50 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <MessageSquare className="h-4 w-4 text-blue-600" />
                <span className="text-xs font-semibold text-blue-900 uppercase">STT</span>
              </div>
              <ProviderRow provider={bundle.stt_provider} model={bundle.stt_model} />
            </div>
            <div className="p-3 bg-purple-50 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <Brain className="h-4 w-4 text-purple-600" />
                <span className="text-xs font-semibold text-purple-900 uppercase">LLM</span>
              </div>
              <ProviderRow
                provider={bundle.llm_provider}
                model={bundle.llm_model}
                extra={llmSummary || null}
              />
            </div>
            <div className="p-3 bg-green-50 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <Volume2 className="h-4 w-4 text-green-600" />
                <span className="text-xs font-semibold text-green-900 uppercase">TTS</span>
              </div>
              <ProviderRow
                provider={bundle.tts_provider}
                model={bundle.tts_model}
                extra={bundle.tts_voice ? `Voice: ${bundle.tts_voice}` : null}
              />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
