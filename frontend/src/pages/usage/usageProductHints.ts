/** Product areas shown separately from call-import drill-down. */
export const CALL_IMPORT_PRODUCT_SECTIONS = new Set([
  'call_imports',
  'call_import_evaluations',
])

/** Short table headline per product section (workspace composite rows). */
export const PRODUCT_SECTION_HEADLINES: Record<string, string> = {
  voice_playground: 'Voice playground',
  playground: 'Playground',
  chat: 'Chat',
  telephony: 'Telephony',
  evaluators: 'Evaluators',
  metrics: 'Metrics',
  judge_alignment: 'Judge alignment',
  prompt_optimization: 'Prompt optimization',
  personas: 'Personas',
  agents: 'Agents',
  prompt_partials: 'Prompt partials',
  conversation_evaluations: 'Conversation evaluations',
  test_agent: 'Test agent',
  call_import_evaluations: 'Call import evaluations',
  call_imports: 'Call imports',
  other: 'Other',
}

export const CALL_IMPORT_BATCH_HEADLINE = 'Call import batch'

export const PRODUCT_SECTION_HINTS: Record<string, string> = {
  voice_playground: 'Voice agent playground — LLM, STT, and TTS',
  playground: 'Text playground and experiments',
  chat: 'Chat conversations',
  telephony: 'Telephony and live calls',
  evaluators: 'Evaluator definitions and runs',
  metrics: 'Metrics and scoring',
  judge_alignment: 'Judge alignment workflows',
  prompt_optimization: 'Prompt optimization jobs',
  personas: 'Persona generation',
  agents: 'Agent configuration',
  prompt_partials: 'Prompt partials',
  conversation_evaluations: 'Conversation evaluations',
  test_agent: 'Test agent sessions',
  other: 'Other product usage',
}

export const CALL_IMPORT_HINT =
  'Call import batch — CSV upload or manual audio recordings'
