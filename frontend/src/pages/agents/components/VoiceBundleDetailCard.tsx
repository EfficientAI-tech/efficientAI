import { Mic, Edit, ExternalLink } from 'lucide-react'
import { VoiceBundle, VoiceBundleType } from '../../../types/api'
import Button from '../../../components/Button'
import { useToast } from '../../../hooks/useToast'
import VoiceBundleParamsModal, { type VoiceBundleParamsMode } from './VoiceBundleParamsModal'

interface VoiceBundleDetailCardProps {
  bundle: VoiceBundle | null | undefined
  onEdit?: () => void
  onManageInVoiceBundles?: () => void
  /**
   * readonly — compact STT/LLM/TTS summary only (view mode).
   * collapsible — summary by default; expand to tune in edit mode.
   * @deprecated Use `paramTuningMode` instead.
   */
  allowParamTuning?: boolean
  paramTuningMode?: VoiceBundleParamsMode
}

export default function VoiceBundleDetailCard({
  bundle,
  onEdit,
  onManageInVoiceBundles,
  allowParamTuning,
  paramTuningMode,
}: VoiceBundleDetailCardProps) {
  const { showToast } = useToast()

  const paramsMode: VoiceBundleParamsMode =
    paramTuningMode ?? (allowParamTuning === false ? 'readonly' : allowParamTuning ? 'collapsible' : 'readonly')

  if (!bundle) {
    return (
      <div className="border border-dashed border-gray-300 rounded-lg p-8 text-center bg-gray-50">
        <Mic className="h-10 w-10 text-gray-300 mx-auto mb-3" />
        <p className="text-sm text-gray-500">No voice bundle configured for this test agent.</p>
        <p className="text-xs text-gray-400 mt-1">Assign a bundle in edit mode to enable test calls.</p>
      </div>
    )
  }

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden bg-white">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gray-50">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-gray-900 truncate">{bundle.name}</h3>
          {bundle.description && (
            <p className="text-sm text-gray-500 mt-0.5 truncate">{bundle.description}</p>
          )}
          <p className="text-xs text-gray-400 mt-0.5 capitalize">
            {bundle.bundle_type === VoiceBundleType.S2S ? 'Speech-to-Speech' : 'STT + LLM + TTS'}
            {!bundle.is_active && ' · Inactive'}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {onEdit && (
            <Button type="button" variant="outline" size="sm" onClick={onEdit} leftIcon={<Edit className="h-4 w-4" />}>
              Full edit
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

      <div className="p-4">
        <VoiceBundleParamsModal bundle={bundle} showToast={showToast} mode={paramsMode} />
      </div>
    </div>
  )
}
