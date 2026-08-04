export const agentSystemPromptTag = (agentId: string) => `__agent_system_prompt__:${agentId}`

export const agentProviderPromptTag = (agentId: string) => `__agent_provider_prompt__:${agentId}`

export function partialMatchesAgentPrompt(
  partial: { tags?: string[] | null },
  agentId: string,
  tag = agentSystemPromptTag(agentId),
): boolean {
  return (partial.tags || []).includes(tag)
}
