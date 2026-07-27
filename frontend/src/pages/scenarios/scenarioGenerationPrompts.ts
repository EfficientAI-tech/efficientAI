export const SCENARIO_GENERATION_SYSTEM_PROMPT =
  'You generate high-quality test scenarios for voice AI agents. Return ONLY valid JSON array with objects: { "name": string, "description": string }.'

export const SCENARIO_DESCRIPTION_SECTIONS = [
  '### Background (2-3 sentences)',
  '### Caller Intent (1-2 sentences)',
  '### Conversation Flow (4-6 numbered steps)',
  '### Success Criteria (2-4 bullet points)',
  '### Edge Cases to Probe (2-3 bullet points)',
] as const

export function buildScenarioGenerationRequirements(): string[] {
  return [
    'Requirements:',
    '- Each scenario must test a different user intent or edge case.',
    '- Keep each name short (under 80 characters).',
    '- Each description must be 150-300 words.',
    '- Each description MUST include all of these markdown sections:',
    ...SCENARIO_DESCRIPTION_SECTIONS.map((section) => `  - ${section}`),
    '- Descriptions should be specific, test-oriented, and suitable for QA evaluation.',
    '- Return only JSON array, no markdown wrapper, no explanation.',
  ]
}

export const SCENARIO_EDIT_GENERATION_SYSTEM_PROMPT =
  'You write detailed, structured scenario descriptions for QA test scenarios. Use the required markdown sections and aim for 150-300 words unless the user request specifies otherwise.'

export function buildScenarioEditGenerationUserPrompt(args: {
  scenarioName: string
  currentDescription: string
  request: string
}): string {
  return [
    `Scenario Name: ${args.scenarioName}`,
    `Current Description: ${args.currentDescription}`,
    `Request: ${args.request}`,
    'Rewrite or extend the scenario description using these required markdown sections:',
    ...SCENARIO_DESCRIPTION_SECTIONS.map((section) => `- ${section}`),
    'Write only the updated scenario description text.',
  ].join('\n')
}

export function buildScenarioGenerationUserPrompt(args: {
  scenarioCount: number
  agentName: string
  language?: string | null
  callType?: string | null
  agentPrompt: string
  additionalContext?: string
}): string {
  return [
    `Generate ${args.scenarioCount} diverse test scenarios from this agent system prompt.`,
    `Agent Name: ${args.agentName}`,
    args.language ? `Language: ${args.language}` : '',
    args.callType ? `Call Type: ${args.callType}` : '',
    `System Prompt:\n${args.agentPrompt}`,
    args.additionalContext?.trim()
      ? `Additional Generation Context:\n${args.additionalContext.trim()}`
      : '',
    ...buildScenarioGenerationRequirements(),
  ]
    .filter(Boolean)
    .join('\n')
}
