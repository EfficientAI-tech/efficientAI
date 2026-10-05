import { Link } from 'react-router-dom'
import { Sparkles } from 'lucide-react'
import AIProviderModelPicker from '../../../components/AIProviderModelPicker'
import type { ProviderModelValue } from '../../../components/providers/ProviderModelPicker'
import { InfoTooltip } from '../../../components/shared'
import { isClassificationCapableModel } from '../../../lib/llmModelOptions'

/**
 * Model picker for classification metrics. These are scored by System 1 (Jev)
 * models only, so the picker is restricted to Jev-capable models.
 */
export default function RunEvaluationClassificationModel({
  value,
  onChange,
  metricNames,
  hasCompatibleCredential,
  complete,
}: {
  value: ProviderModelValue
  onChange: (next: ProviderModelValue) => void
  metricNames: string[]
  hasCompatibleCredential: boolean
  complete: boolean
}) {
  const update = (patch: Partial<ProviderModelValue>) => onChange({ ...value, ...patch })
  return (
    <div
      className={`rounded-md border p-3 space-y-2 ${
        complete ? 'border-violet-200 bg-violet-50/40' : 'border-amber-300 bg-amber-50/40'
      }`}
    >
      <div className="flex items-center gap-1.5">
        <Sparkles className="h-3.5 w-3.5 text-violet-600" />
        <p className="text-xs uppercase tracking-wide font-semibold text-violet-800">
          Classification model · System 1
        </p>
        <InfoTooltip title="Why a separate model?" placement="bottom" widthClassName="w-72">
          Classification metrics (Noul, Choice, Score) are answered by System 1 (Jev) models,
          which return calibrated probabilities instead of free-text judgements. Standard LLM
          judges cannot score them, and Jev models cannot score standard metrics.
        </InfoTooltip>
      </div>
      <p className="text-[11px] text-gray-600">
        Scores {metricNames.length} classification metric{metricNames.length === 1 ? '' : 's'}:{' '}
        <span className="font-medium text-gray-800">{metricNames.join(', ')}</span>. Only System 1
        models (for example <code className="font-mono">typesafe/jev-1.13.0</code>) are listed.
      </p>
      <AIProviderModelPicker
        provider={value.provider ?? ''}
        model={value.model ?? ''}
        credentialId={value.credential_id ?? ''}
        onSelectionChange={(next) =>
          update({
            provider: next.provider || null,
            model: next.model || null,
            credential_id: next.credentialId || null,
          })
        }
        onProviderChange={(next) => update({ provider: next || null })}
        onCredentialIdChange={(next) => update({ credential_id: next || null })}
        onModelChange={(next) => update({ model: next || null })}
        llm_config={value.llm_config ?? null}
        onLLMConfigChange={(llm_config) => update({ llm_config })}
        modelFilter={isClassificationCapableModel}
        incompatibleHint="No System 1 (Jev) models on this credential. Choose another credential or enable a Jev model in Integrations."
        size="sm"
      />
      {!hasCompatibleCredential && (
        <p className="text-[11px] text-amber-800">
          No System 1 model is configured.{' '}
          <Link to="/integrations" className="font-medium underline hover:text-amber-900">
            Add an OpenRouter or TypeSafe credential
          </Link>{' '}
          with a Jev model to score classification metrics.
        </p>
      )}
      {hasCompatibleCredential && !complete && (
        <p className="text-[11px] text-amber-800">Pick a System 1 model to run classification metrics.</p>
      )}
    </div>
  )
}
