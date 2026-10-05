import type { AgentMediumFilter } from '../../lib/agentMedium'

export type ScenarioGenerationModality = AgentMediumFilter

const VOICE_SCENARIO_SECTIONS = [
  '### Background (2-3 sentences)',
  '### Caller intent (1-2 sentences)',
  '### Conversation flow (4-6 numbered steps)',
  '### Success criteria (2-4 bullet points)',
  '### Edge cases to probe (2-3 bullet points)',
] as const

const CHAT_SCENARIO_SECTIONS = [
  '### Background (2-3 sentences)',
  '### Customer intent (1-2 sentences)',
  '### Conversation flow (4-6 numbered steps)',
  '### Success criteria (2-4 bullet points)',
  '### Edge cases to probe (2-3 bullet points)',
] as const

export function scenarioDescriptionSections(modality: ScenarioGenerationModality) {
  return modality === 'chat' ? CHAT_SCENARIO_SECTIONS : VOICE_SCENARIO_SECTIONS
}

export function scenarioGenerationSystemPrompt(modality: ScenarioGenerationModality): string {
  if (modality === 'chat') {
    return (
      'You generate high-quality test scenarios for text chat AI agents (messaging UI, not phone calls). ' +
      'Use customer/user language only — never caller, phone call, dial, or hang up. ' +
      'Return ONLY valid JSON array with objects: { "name": string, "description": string, "goal": string }.'
    )
  }
  return (
    'You generate high-quality test scenarios for voice AI agents. ' +
    'Return ONLY valid JSON array with objects: { "name": string, "description": string, "goal": string }.'
  )
}

export function buildScenarioGenerationRequirements(modality: ScenarioGenerationModality): string[] {
  const sections = scenarioDescriptionSections(modality)
  const lines = [
    'Requirements:',
    '- Each scenario must test a different user intent or edge case.',
    '- Keep each name short (under 80 characters).',
    '- Each description must be 150-300 words.',
    '- Each description MUST include all of these markdown sections:',
    ...sections.map((section) => `  - ${section}`),
  ]
  if (modality === 'chat') {
    lines.push(
      '- Descriptions are for TEXT CHAT: messages, typing, and chat threads.',
      '- Refer to the human side as the customer or user, not caller.',
      '- End the interaction by closing the chat, not hanging up.',
      '- Include a concise goal string for what the customer should achieve in chat.',
    )
  } else {
    lines.push(
      '- Descriptions should reflect a spoken phone or web voice conversation.',
      '- Include a concise goal string summarizing what the caller should achieve.',
    )
  }
  lines.push(
    '- Descriptions should be specific, test-oriented, and suitable for QA evaluation.',
    '- Return only JSON array, no markdown wrapper, no explanation.',
  )
  return lines
}

export function scenarioEditGenerationSystemPrompt(modality: ScenarioGenerationModality): string {
  const channel = modality === 'chat' ? 'text chat' : 'voice'
  return (
    `You write detailed, structured scenario descriptions for QA test scenarios (${channel}). ` +
    'Use the required markdown sections and aim for 150-300 words unless the user request specifies otherwise.'
  )
}

export const SCENARIO_GENERATION_SYSTEM_PROMPT = scenarioGenerationSystemPrompt('voice')

export const SCENARIO_DESCRIPTION_SECTIONS = VOICE_SCENARIO_SECTIONS

export const SCENARIO_EDIT_GENERATION_SYSTEM_PROMPT = scenarioEditGenerationSystemPrompt('voice')

export function buildScenarioEditGenerationUserPrompt(args: {
  scenarioName: string
  currentDescription: string
  request: string
  modality?: ScenarioGenerationModality
}): string {
  const modality = args.modality ?? 'voice'
  return [
    `Scenario Name: ${args.scenarioName}`,
    `Current Description: ${args.currentDescription}`,
    `Request: ${args.request}`,
    modality === 'chat'
      ? 'Channel: text chat (use customer/user language, not caller or phone call).'
      : 'Channel: voice.',
    'Rewrite or extend the scenario description using these required markdown sections:',
    ...scenarioDescriptionSections(modality).map((section) => `- ${section}`),
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
  modality?: ScenarioGenerationModality
}): string {
  const modality = args.modality ?? 'voice'
  return [
    `Generate ${args.scenarioCount} diverse test scenarios from this agent system prompt.`,
    `Agent Name: ${args.agentName}`,
    `Channel: ${modality === 'chat' ? 'text chat' : 'voice'}`,
    args.language ? `Language: ${args.language}` : '',
    args.callType ? `Call Type: ${args.callType}` : '',
    `System Prompt:\n${args.agentPrompt}`,
    args.additionalContext?.trim()
      ? `Additional Generation Context:\n${args.additionalContext.trim()}`
      : '',
    ...buildScenarioGenerationRequirements(modality),
  ]
    .filter(Boolean)
    .join('\n')
}
