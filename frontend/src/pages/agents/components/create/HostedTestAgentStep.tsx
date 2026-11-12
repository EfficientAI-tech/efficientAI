import { Loader2, Sparkles } from 'lucide-react'

import LlmCredentialAnchoredFields from '../../../../components/providers/LlmCredentialAnchoredFields'
import type { AIProvider } from '../../../../types/api'
import AgentKnowledgeBasesPanel from '../AgentKnowledgeBasesPanel'
import type { KnowledgeBaseSummary } from '../../../knowledgeBases/knowledgeBaseTypes'
import TestAgentTemplateEditor from '../TestAgentTemplateEditor'
import {
  type TestAgentTemplateDraft,
  assembleTestAgentPrompt,
  isTemplateFilled,
} from '../agentTestSetupConstants'
import type { CreateAgentFormData } from './createAgentTypes'
import HostedWizardSplitLayout from './HostedWizardSplitLayout'

interface HostedTestAgentStepProps {
  formData: CreateAgentFormData
  onFormChange: (patch: Partial<CreateAgentFormData>) => void
  productionPrompt: string
  testAgentTemplate: TestAgentTemplateDraft
  onTestAgentTemplateChange: (value: TestAgentTemplateDraft) => void
  additionalContext: string
  onAdditionalContextChange: (value: string) => void
  knowledgeBases: KnowledgeBaseSummary[]
  aiProviders: AIProvider[]
  aiCredentialId: string
  onAiCredentialIdChange: (value: string) => void
  aiModel: string
  onAiModelChange: (value: string) => void
  onGenerateTestPrompt: () => void
  isGenerating: boolean
  canGenerate: boolean
}

export function validateHostedTestStep(testAgentTemplate: TestAgentTemplateDraft): boolean {
  if (!isTemplateFilled(testAgentTemplate)) return false
  return Boolean(testAgentTemplate.generated_from_production)
}

export function hostedTestStepValidationMessage(testAgentTemplate: TestAgentTemplateDraft): string {
  if (!isTemplateFilled(testAgentTemplate)) {
    return 'Test agent prompt must be at least 10 words.'
  }
  if (!testAgentTemplate.generated_from_production) {
    return 'Use “Generate from production” to create the test agent before continuing.'
  }
  return 'Complete the test agent step.'
}

export default function HostedTestAgentStep({
  formData,
  onFormChange,
  productionPrompt,
  testAgentTemplate,
  onTestAgentTemplateChange,
  additionalContext,
  onAdditionalContextChange,
  knowledgeBases,
  aiProviders,
  aiCredentialId,
  onAiCredentialIdChange,
  aiModel,
  onAiModelChange,
  onGenerateTestPrompt,
  isGenerating,
  canGenerate,
}: HostedTestAgentStepProps) {
  const activeProviders = aiProviders.filter((p) => p.is_active)
  const assembledPrompt = assembleTestAgentPrompt(testAgentTemplate.sections)
  const wordCount = assembledPrompt.trim().split(/\s+/).filter(Boolean).length

  return (
    <HostedWizardSplitLayout
      title="Test agent"
      subtitle="Generate the simulated customer on the right; edit the template on the left."
      leftTitle="Test agent template"
      leftHint={
        testAgentTemplate.generated_from_production
          ? `${wordCount} words assembled`
          : 'Generate from production →'
      }
      left={
        <div className="h-full min-h-[260px] overflow-y-auto p-3 lg:min-h-0">
          <TestAgentTemplateEditor template={testAgentTemplate} onChange={onTestAgentTemplateChange} />
        </div>
      }
      right={
        <>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Production prompt (reference)</label>
            <div className="max-h-28 overflow-y-auto rounded-lg border border-gray-200 bg-white p-2 text-xs text-gray-600 whitespace-pre-wrap">
              {productionPrompt.trim() || '—'}
            </div>
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 space-y-3">
            <LlmCredentialAnchoredFields
              credentialId={aiCredentialId}
              model={aiModel}
              activeProviders={activeProviders}
              onCredentialChange={(id) => {
                onAiCredentialIdChange(id)
                onAiModelChange('')
              }}
              onModelChange={onAiModelChange}
              credentialLabel="Generation model"
            />
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Additional context (optional)</label>
              <textarea
                value={additionalContext}
                onChange={(e) => onAdditionalContextChange(e.target.value)}
                rows={2}
                placeholder="Industry, compliance, test priorities…"
                className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white"
              />
            </div>
            <button
              type="button"
              onClick={onGenerateTestPrompt}
              disabled={isGenerating || !canGenerate}
              className="inline-flex w-full items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Generating…
                </>
              ) : (
                <>
                  <Sparkles className="h-3.5 w-3.5" />
                  Generate from production
                </>
              )}
            </button>
          </div>
          <AgentKnowledgeBasesPanel
            compact
            mode="edit"
            side="test"
            attachedIds={formData.test_knowledge_base_ids}
            knowledgeBases={knowledgeBases}
            onChange={(ids) => onFormChange({ test_knowledge_base_ids: ids })}
          />
          <p
            className={`text-xs ${
              testAgentTemplate.generated_from_production && wordCount >= 10
                ? 'text-green-600'
                : 'text-gray-500'
            }`}
          >
            {testAgentTemplate.generated_from_production
              ? 'Template ready — tune sections on the left.'
              : 'Generate from production before continuing.'}
          </p>
        </>
      }
    />
  )
}
