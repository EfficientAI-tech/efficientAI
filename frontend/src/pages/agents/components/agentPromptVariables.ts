export type AgentPromptVariableDef = {
  key: string
  label: string
  description?: string
  builtin?: boolean
}

/** Built-in placeholders for test agent prompts (substitution at runtime is future work). */
export const BUILTIN_AGENT_PROMPT_VARIABLES: AgentPromptVariableDef[] = [
  {
    key: 'agent_name',
    label: 'Agent name',
    description: "This test agent's display name",
    builtin: true,
  },
  {
    key: 'agent_language',
    label: 'Agent language',
    description: 'Primary language code (e.g. en)',
    builtin: true,
  },
  {
    key: 'call_type',
    label: 'Call type',
    description: 'inbound or outbound',
    builtin: true,
  },
  {
    key: 'call_medium',
    label: 'Call medium',
    description: 'phone_call or web_call',
    builtin: true,
  },
  {
    key: 'caller_phone',
    label: 'Caller phone',
    description: 'Caller number when available on a live call',
    builtin: true,
  },
  {
    key: 'scenario_name',
    label: 'Scenario name',
    description: 'Active test scenario name during an evaluator run',
    builtin: true,
  },
]

const BUILTIN_KEYS = new Set(BUILTIN_AGENT_PROMPT_VARIABLES.map((v) => v.key))

export function mergeAgentPromptVariables(
  customVariables: Record<string, string> | null | undefined
): AgentPromptVariableDef[] {
  const custom: AgentPromptVariableDef[] = Object.entries(customVariables || {})
    .filter(([key]) => key.trim() && !BUILTIN_KEYS.has(key.trim()))
    .map(([key, description]) => ({
      key: key.trim(),
      label: key.trim(),
      description: description?.trim() || undefined,
      builtin: false,
    }))
  return [...BUILTIN_AGENT_PROMPT_VARIABLES, ...custom]
}

export function variablePlaceholder(key: string): string {
  return `{${key}}`
}
