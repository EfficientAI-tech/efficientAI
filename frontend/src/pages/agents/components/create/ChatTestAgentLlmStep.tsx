import AIProviderModelPicker from '../../../../components/AIProviderModelPicker'
import { isLLMSelectionComplete } from '../../../../lib/llmModelOptions'
import type { AIProvider } from '../../../../types/api'
import { WizardStepHeader } from './WizardStepHeader'
import type { ChatConnectionForm } from './ChatConnectionStep'

interface ChatTestAgentLlmStepProps {
  value: Pick<ChatConnectionForm, 'testLlmProvider' | 'testLlmCredentialId' | 'testLlmModel'>
  onChange: (patch: Partial<ChatConnectionForm>) => void
  embedded?: boolean
}

export function validateTestAgentLlm(
  value: Pick<
    ChatConnectionForm,
    'testLlmProvider' | 'testLlmCredentialId' | 'testLlmModel'
  >,
  aiProviders: AIProvider[] = [],
): boolean {
  return isLLMSelectionComplete(
    {
      provider: value.testLlmProvider,
      model: value.testLlmModel,
      credential_id: value.testLlmCredentialId,
    },
    aiProviders,
  )
}

export function testAgentLlmValidationMessage(): string {
  return 'Select a credential and model.'
}

export function applyTestAgentLlmPayload(
  payload: Record<string, unknown>,
  value: Pick<ChatConnectionForm, 'testLlmProvider' | 'testLlmCredentialId' | 'testLlmModel'>,
  aiProviders: AIProvider[] = [],
): void {
  if (
    !isLLMSelectionComplete(
      {
        provider: value.testLlmProvider,
        model: value.testLlmModel,
        credential_id: value.testLlmCredentialId,
      },
      aiProviders,
    )
  ) {
    return
  }
  payload.test_llm_provider = value.testLlmProvider
  const model =
    value.testLlmModel.trim() ||
    (() => {
      const cred = aiProviders.find((p) => p.id === value.testLlmCredentialId)
      return cred?.gateway_model?.trim() || ''
    })()
  if (!model) return
  payload.test_llm_model = model
  if (value.testLlmCredentialId) {
    payload.test_llm_credential_id = value.testLlmCredentialId
  }
}

export default function ChatTestAgentLlmStep({
  value,
  onChange,
  embedded,
}: ChatTestAgentLlmStepProps) {
  return (
    <div className={embedded ? 'w-full space-y-4' : 'w-full max-w-3xl mx-auto space-y-6'}>
      {!embedded ? (
        <WizardStepHeader
          title="Test agent model"
          subtitle="Provider and model for the customer role in evals."
        />
      ) : (
        <div className="mb-1">
          <h3 className="text-sm font-medium text-gray-900">Language model</h3>
          <p className="text-xs text-gray-500 mt-0.5">Customer role in chat evals.</p>
        </div>
      )}
      <AIProviderModelPicker
        provider={value.testLlmProvider}
        model={value.testLlmModel}
        credentialId={value.testLlmCredentialId}
        onProviderChange={(provider) =>
          onChange({ testLlmProvider: provider, testLlmModel: '', testLlmCredentialId: '' })
        }
        onModelChange={(model) => onChange({ testLlmModel: model })}
        onCredentialIdChange={(credentialId) => onChange({ testLlmCredentialId: credentialId })}
        onSelectionChange={(next) =>
          onChange({
            testLlmProvider: next.provider,
            testLlmModel: next.model,
            testLlmCredentialId: next.credentialId,
          })
        }
        size="md"
        showAdvancedOptions={false}
      />
    </div>
  )
}
