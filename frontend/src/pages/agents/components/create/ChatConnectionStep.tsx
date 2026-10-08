import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../../lib/api'
import { AIProvider } from '../../../../types/api'
import LlmCredentialAnchoredFields from '../../../../components/providers/LlmCredentialAnchoredFields'
import { isLLMSelectionComplete } from '../../../../lib/llmModelOptions'

export type ChatConnectionType =
  | 'internal_llm'
  | 'provider_chat'
  | 'customer_api'
  | 'customer_websocket'
  | 'messaging_channels'

export type ChatConnectionForm = {
  connectionType: ChatConnectionType
  mainLlmProvider: string
  mainLlmCredentialId: string
  mainLlmModel: string
  useSeparateTestLlm: boolean
  testLlmProvider: string
  testLlmCredentialId: string
  testLlmModel: string
}

export type ChatEvalMode = 'pre_prod_sim' | 'post_prod_live' | 'post_prod_import'

interface ChatConnectionStepProps {
  value: ChatConnectionForm
  onChange: (patch: Partial<ChatConnectionForm>) => void
  variant?: 'create' | 'compact'
  chatEvalMode?: ChatEvalMode
  onChatEvalModeChange?: (mode: ChatEvalMode) => void
}

export function validateChatConnection(
  value: ChatConnectionForm,
  aiProviders: AIProvider[] = [],
): boolean {
  if (value.connectionType !== 'internal_llm') {
    return true
  }
  return isLLMSelectionComplete(
    {
      provider: value.mainLlmProvider,
      model: value.mainLlmModel,
      credential_id: value.mainLlmCredentialId,
    },
    aiProviders,
  )
}

export function chatConnectionValidationMessage(_value: ChatConnectionForm): string {
  return 'Select API credential and model for the chat agent.'
}

function LlmCredentialModelFields({
  title,
  hint,
  credentialId,
  model,
  onCredentialChange,
  onModelChange,
  activeProviders,
}: {
  title: string
  hint?: string
  credentialId: string
  model: string
  onCredentialChange: (credentialId: string, provider: string) => void
  onModelChange: (model: string) => void
  activeProviders: AIProvider[]
}) {
  return (
    <div className="border border-gray-200 rounded-lg p-3 space-y-2.5 bg-white">
      <div>
        <h4 className="text-xs font-semibold text-gray-900">{title}</h4>
        {hint ? <p className="text-xs text-gray-500 mt-0.5">{hint}</p> : null}
      </div>
      <LlmCredentialAnchoredFields
        credentialId={credentialId}
        model={model}
        activeProviders={activeProviders}
        onCredentialChange={onCredentialChange}
        onModelChange={onModelChange}
      />
    </div>
  )
}

export default function ChatConnectionStep({
  value,
  onChange,
  variant: _variant = 'create',
}: ChatConnectionStepProps) {
  const { data: aiProviders = [] } = useQuery({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const activeProviders = aiProviders.filter((p: AIProvider) => p.is_active)

  if (value.connectionType !== 'internal_llm') {
    return null
  }

  return (
    <div className="w-full space-y-4">
      <LlmCredentialModelFields
        title="Chat Agent"
        credentialId={value.mainLlmCredentialId}
        model={value.mainLlmModel}
        activeProviders={activeProviders}
        onCredentialChange={(id, provider) =>
          onChange({ mainLlmCredentialId: id, mainLlmProvider: provider, mainLlmModel: '' })
        }
        onModelChange={(m) => onChange({ mainLlmModel: m })}
      />
    </div>
  )
}
