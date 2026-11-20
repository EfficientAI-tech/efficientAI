import AIProviderModelPicker from '../../../../components/AIProviderModelPicker'
import type { LLMGenerationConfig } from '../../../../config/llmGenerationParams'

type StudioWizardLlmStepProps = {
  runName: string
  onRunNameChange: (value: string) => void
  transcriptSource: 'production' | 'diarised'
  onTranscriptSourceChange: (value: 'production' | 'diarised') => void
  llmProvider: string
  llmModel: string
  llmCredentialId: string
  llmConfig: LLMGenerationConfig
  onProviderChange: (value: string) => void
  onModelChange: (value: string) => void
  onCredentialIdChange: (value: string) => void
  onLLMConfigChange: (value: LLMGenerationConfig | null) => void
}

export default function StudioWizardLlmStep({
  runName,
  onRunNameChange,
  transcriptSource,
  onTranscriptSourceChange,
  llmProvider,
  llmModel,
  llmCredentialId,
  llmConfig,
  onProviderChange,
  onModelChange,
  onCredentialIdChange,
  onLLMConfigChange,
}: StudioWizardLlmStepProps) {
  return (
    <div className="space-y-6 overflow-y-auto pr-1">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-3xl">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Run name</label>
          <input
            value={runName}
            onChange={(e) => onRunNameChange(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            placeholder="Optional label"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Transcript source</label>
          <select
            value={transcriptSource}
            onChange={(e) =>
              onTranscriptSourceChange(e.target.value as 'production' | 'diarised')
            }
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="diarised">Diarised</option>
            <option value="production">Production (CSV)</option>
          </select>
        </div>
      </div>
      <div>
        <h3 className="text-sm font-medium text-gray-900 mb-2">Evaluation model</h3>
        <p className="text-xs text-gray-500 mb-4">
          Leave blank to use your organization default. Pick a credential to pin gateway routing.
        </p>
        <AIProviderModelPicker
          provider={llmProvider}
          model={llmModel}
          credentialId={llmCredentialId}
          llm_config={llmConfig}
          onProviderChange={onProviderChange}
          onModelChange={onModelChange}
          onCredentialIdChange={onCredentialIdChange}
          onLLMConfigChange={(next) => onLLMConfigChange(next ?? {})}
        />
      </div>
    </div>
  )
}
