import { Loader2, Sparkles } from 'lucide-react'

import LlmCredentialAnchoredFields from '../../../../components/providers/LlmCredentialAnchoredFields'
import type { AIProvider } from '../../../../types/api'
import AgentKnowledgeBasesPanel from '../AgentKnowledgeBasesPanel'
import type { KnowledgeBaseSummary } from '../../../knowledgeBases/knowledgeBaseTypes'
import type { CreateAgentFormData } from './createAgentTypes'
import HostedWizardSplitLayout, { HostedPromptTextarea } from './HostedWizardSplitLayout'
import { CREATE_WIZARD_FIELD_CLASS, CREATE_WIZARD_LABEL_CLASS } from './createWizardUi'

interface HostedProductionAgentStepProps {
  formData: CreateAgentFormData
  onFormChange: (patch: Partial<CreateAgentFormData>) => void
  brief: string
  onBriefChange: (value: string) => void
  productionPrompt: string
  onProductionPromptChange: (value: string) => void
  productionPromptAiGenerated: boolean
  knowledgeBases: KnowledgeBaseSummary[]
  aiProviders: AIProvider[]
  aiCredentialId: string
  onAiCredentialIdChange: (value: string) => void
  aiModel: string
  onAiModelChange: (value: string) => void
  onGenerateProduction: () => void
  isGenerating: boolean
  canGenerate: boolean
}

export function validateHostedProductionStep(
  formData: CreateAgentFormData,
  productionPrompt: string,
  productionPromptAiGenerated: boolean,
): boolean {
  if (!formData.name.trim()) return false
  if (!productionPromptAiGenerated) return false
  const words = productionPrompt.trim().split(/\s+/).filter(Boolean).length
  return words >= 10
}

export function hostedProductionStepValidationMessage(
  formData: CreateAgentFormData,
  productionPrompt: string,
  productionPromptAiGenerated: boolean,
): string {
  if (!formData.name.trim()) return 'Agent name is required.'
  if (!productionPromptAiGenerated) {
    return 'Use “Generate production prompt” before continuing.'
  }
  const words = productionPrompt.trim().split(/\s+/).filter(Boolean).length
  if (words < 10) return 'Production prompt must be at least 10 words.'
  return 'Complete the production agent step.'
}

export default function HostedProductionAgentStep({
  formData,
  onFormChange,
  brief,
  onBriefChange,
  productionPrompt,
  onProductionPromptChange,
  productionPromptAiGenerated,
  knowledgeBases,
  aiProviders,
  aiCredentialId,
  onAiCredentialIdChange,
  aiModel,
  onAiModelChange,
  onGenerateProduction,
  isGenerating,
  canGenerate,
}: HostedProductionAgentStepProps) {
  const activeProviders = aiProviders.filter((p) => p.is_active)

  return (
    <HostedWizardSplitLayout
      title="Production agent"
      subtitle="Configure on the right; the generated system prompt appears on the left."
      leftTitle="Production system prompt"
      leftHint={
        productionPromptAiGenerated ? 'Editable after generation' : 'Generate from your brief →'
      }
      left={
        <HostedPromptTextarea
          value={productionPrompt}
          onChange={onProductionPromptChange}
          placeholder="Your production system prompt will appear here after generation."
        />
      }
      right={
        <>
          <div className="grid grid-cols-1 gap-3">
            <div>
              <label className={CREATE_WIZARD_LABEL_CLASS}>Name *</label>
              <input
                type="text"
                required
                className={CREATE_WIZARD_FIELD_CLASS}
                value={formData.name}
                onChange={(e) => onFormChange({ name: e.target.value })}
                placeholder="Customer Support Bot"
              />
            </div>
            <div>
              <label className={CREATE_WIZARD_LABEL_CLASS}>Language</label>
              <select
                className={CREATE_WIZARD_FIELD_CLASS}
                value={formData.language}
                onChange={(e) => onFormChange({ language: e.target.value })}
              >
                <option value="en">English</option>
                <option value="hi">Hindi</option>
                <option value="es">Spanish</option>
                <option value="fr">French</option>
                <option value="de">German</option>
              </select>
            </div>
          </div>
          <div>
            <label className={CREATE_WIZARD_LABEL_CLASS}>What should this agent do? *</label>
            <textarea
              className={`${CREATE_WIZARD_FIELD_CLASS} min-h-[88px] resize-y text-sm`}
              value={brief}
              onChange={(e) => onBriefChange(e.target.value)}
              placeholder="Brief for the AI — role, policies, tone…"
              rows={3}
            />
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 space-y-3">
            <p className="text-xs font-medium text-gray-700">Generation model</p>
            <LlmCredentialAnchoredFields
              credentialId={aiCredentialId}
              model={aiModel}
              activeProviders={activeProviders}
              onCredentialChange={(id) => {
                onAiCredentialIdChange(id)
                onAiModelChange('')
              }}
              onModelChange={onAiModelChange}
              credentialLabel="AI Provider"
            />
            <button
              type="button"
              onClick={onGenerateProduction}
              disabled={isGenerating || !canGenerate}
              className="inline-flex w-full items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Generating…
                </>
              ) : (
                <>
                  <Sparkles className="h-3.5 w-3.5" />
                  Generate production prompt
                </>
              )}
            </button>
          </div>
          <AgentKnowledgeBasesPanel
            compact
            mode="edit"
            side="production"
            attachedIds={formData.knowledge_base_ids}
            knowledgeBases={knowledgeBases}
            onChange={(ids) => onFormChange({ knowledge_base_ids: ids })}
          />
          <p
            className={`text-xs ${
              productionPromptAiGenerated ? 'text-green-600' : 'text-gray-500'
            }`}
          >
            {productionPromptAiGenerated
              ? 'Prompt generated — refine on the left if needed.'
              : 'You must generate the prompt before continuing.'}
          </p>
        </>
      }
    />
  )
}
