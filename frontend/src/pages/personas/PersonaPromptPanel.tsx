import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { FileText, Loader2, Sparkles } from 'lucide-react'
import { apiClient } from '../../lib/api'
import AIGeneratePanel from '../../components/shared/AIGeneratePanel'
import type { LLMGenerationConfig } from '../../config/llmGenerationParams'

interface PersonaPromptPanelProps {
  value: string
  onChange: (value: string) => void
  personaName?: string
  personaGender?: string
  embedded?: boolean
}

export default function PersonaPromptPanel({
  value,
  onChange,
  personaName,
  personaGender,
  embedded = false,
}: PersonaPromptPanelProps) {
  const [selectedAgentId, setSelectedAgentId] = useState('')
  const [showAiPanel, setShowAiPanel] = useState(false)

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  const {
    data: promptSources,
    isFetching: isLoadingSources,
    refetch: refetchSources,
  } = useQuery({
    queryKey: ['persona-agent-prompt-sources', selectedAgentId],
    queryFn: () => apiClient.getPersonaAgentPromptSources(selectedAgentId),
    enabled: !!selectedAgentId,
  })

  const hasTestAgentPrompt = Boolean(promptSources?.test_agent_prompt?.trim())

  const seedMutation = useMutation({
    mutationFn: async () => {
      if (!selectedAgentId) {
        throw new Error('Select an agent first')
      }
      const sources =
        promptSources ?? (await apiClient.getPersonaAgentPromptSources(selectedAgentId))
      const text = sources.test_agent_prompt
      if (!text?.trim()) {
        throw new Error('This agent has no test agent prompt')
      }
      return text.trim()
    },
    onSuccess: (text) => {
      onChange(text)
    },
  })

  const labelClass = embedded ? 'text-xs font-medium text-gray-600' : 'text-sm font-medium text-gray-700'
  const textareaClass = embedded
    ? 'w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent resize-none'
    : 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent text-sm'

  const handleAgentChange = (agentId: string) => {
    setSelectedAgentId(agentId)
    setShowAiPanel(false)
    if (agentId) {
      void refetchSources()
    }
  }

  const canUseTestAgentPrompt =
    Boolean(selectedAgentId) && !isLoadingSources && hasTestAgentPrompt

  return (
    <div className="space-y-3">
      <div>
        <label className={`block ${labelClass} mb-1`}>Seed from agent</label>
        <select
          value={selectedAgentId}
          onChange={(e) => handleAgentChange(e.target.value)}
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white"
        >
          <option value="">Select an agent…</option>
          {agents.map((agent: { id: string; name: string }) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!canUseTestAgentPrompt || seedMutation.isPending}
          onClick={() => seedMutation.mutate()}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          {seedMutation.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <FileText className="h-3.5 w-3.5" />
          )}
          Use test agent prompt
        </button>
        <button
          type="button"
          disabled={!canUseTestAgentPrompt}
          onClick={() => setShowAiPanel((v) => !v)}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100 disabled:opacity-50"
        >
          <Sparkles className="h-3.5 w-3.5" />
          {showAiPanel ? 'Hide AI generate' : 'Generate with AI'}
        </button>
      </div>

      {isLoadingSources && selectedAgentId ? (
        <p className="text-xs text-gray-500">Loading agent prompts…</p>
      ) : null}

      {selectedAgentId && !isLoadingSources && !hasTestAgentPrompt ? (
        <p className="text-xs text-amber-700">
          This agent has no test agent prompt. Configure one on the agent&apos;s Test Agent tab first.
        </p>
      ) : null}

      {seedMutation.isError ? (
        <p className="text-xs text-red-600">
          {(seedMutation.error as Error)?.message || 'Failed to load prompt'}
        </p>
      ) : null}

      {showAiPanel && canUseTestAgentPrompt ? (
        <AIGeneratePanel
          title="Generate persona prompt from test agent"
          placeholder="Optional: describe caller personality, tone, or scenario context…"
          showToneAndFormat={false}
          requireDescription={false}
          onCancel={() => setShowAiPanel(false)}
          onGenerate={(content) => {
            onChange(content)
            setShowAiPanel(false)
          }}
          generateFn={async (params: {
            description: string
            provider?: string
            model?: string
            llm_config?: LLMGenerationConfig | null
          }) => {
            const result = await apiClient.generatePersonaPrompt({
              agent_id: selectedAgentId,
              source: 'test_agent',
              persona_name: personaName?.trim() || undefined,
              persona_gender: personaGender || undefined,
              additional_context: params.description.trim() || undefined,
              provider: params.provider,
              model: params.model,
              llm_config: params.llm_config ?? undefined,
            })
            return { content: result.persona_prompt }
          }}
        />
      ) : null}

      <div>
        <label className={`block ${labelClass} mb-1`}>Persona prompt</label>
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={embedded ? 6 : 5}
          placeholder="Describe how this caller speaks and behaves during test calls..."
          className={textareaClass}
        />
        <p className="text-xs text-gray-500 mt-1">
          Appended to the test caller system prompt during synthetic evaluation calls.
        </p>
      </div>
    </div>
  )
}
