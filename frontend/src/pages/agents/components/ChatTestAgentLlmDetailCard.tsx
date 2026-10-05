import { Brain } from 'lucide-react'
import { getProviderLabel, getProviderLogo } from '../../../config/providers'
import { ModelProvider, type TestAgent } from '../../../types/api'

function providerEnum(raw?: string | null): ModelProvider | null {
  if (!raw?.trim()) return null
  const key = raw.trim().toLowerCase()
  return (Object.values(ModelProvider) as string[]).includes(key)
    ? (key as ModelProvider)
    : null
}

interface ChatTestAgentLlmDetailCardProps {
  agent: TestAgent
}

export function chatTestAgentLlmConfigured(agent: TestAgent): boolean {
  return Boolean(agent.test_llm_provider?.trim() && agent.test_llm_model?.trim())
}

export default function ChatTestAgentLlmDetailCard({ agent }: ChatTestAgentLlmDetailCardProps) {
  const provider = providerEnum(agent.test_llm_provider)
  const model = agent.test_llm_model?.trim() || ''
  const configured = chatTestAgentLlmConfigured(agent)

  if (!configured) {
    return (
      <div className="border border-dashed border-gray-300 rounded-lg p-8 text-center bg-gray-50">
        <Brain className="h-10 w-10 text-gray-300 mx-auto mb-3" />
        <p className="text-sm text-gray-600">No model configured.</p>
        <p className="text-xs text-gray-400 mt-1 max-w-sm mx-auto">
          Edit this agent and set a credential and model on the Test Agent tab.
        </p>
      </div>
    )
  }

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
        <h3 className="text-base font-semibold text-gray-900">Language model</h3>
        <p className="text-xs text-gray-500 mt-0.5">Customer role in chat evals.</p>
      </div>
      <div className="p-4">
        <section className="rounded-lg border border-purple-100 bg-purple-50/30 p-4 space-y-3">
          <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Brain className="h-4 w-4 text-purple-600" />
            Language model (LLM)
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <p className="block text-xs font-medium text-gray-600 mb-1">Provider</p>
              <div className="flex items-center gap-2 text-sm text-gray-800 bg-white border border-gray-200 rounded-lg px-3 py-2 min-h-[2.5rem]">
                {provider && getProviderLogo(provider) ? (
                  <img
                    src={getProviderLogo(provider)!}
                    alt=""
                    className="h-5 w-5 object-contain shrink-0"
                  />
                ) : null}
                <span className="truncate">
                  {provider ? getProviderLabel(provider) : agent.test_llm_provider || '—'}
                </span>
              </div>
            </div>
            <div>
              <p className="block text-xs font-medium text-gray-600 mb-1">Model</p>
              <div className="text-sm text-gray-800 bg-white border border-gray-200 rounded-lg px-3 py-2 min-h-[2.5rem] flex items-center">
                <span className="truncate font-mono text-xs sm:text-sm">{model}</span>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
