export const CANONICAL_TEST_PROMPT_SECTIONS = [
  { key: 'complementary_goal', title: 'Role and Goal' },
  { key: 'talking_style', title: 'Talking Style' },
  { key: 'questions_to_ask', title: 'Questions to Ask' },
  { key: 'information_to_relay', title: 'Information to Relay' },
  { key: 'constraints', title: 'Constraints' },
] as const

export type TestPromptSectionKey = (typeof CANONICAL_TEST_PROMPT_SECTIONS)[number]['key']

export type ProductionFirstMessageMode =
  | 'assistant_speaks_first'
  | 'assistant_waits_for_user'
  | 'assistant_speaks_first_model_generated'

export type CallerFirstMessageMode = 'wait' | 'speak_first'

export interface TestPromptSectionDraft {
  key: TestPromptSectionKey
  title: string
  content: string
}

export interface TestAgentFirstMessageDraft {
  production_mode: ProductionFirstMessageMode
  production_message?: string | null
  caller_mode: CallerFirstMessageMode
  caller_message?: string | null
}

/** Wire/API shape — modes arrive as plain strings from the backend. */
export interface TestAgentFirstMessageInput {
  production_mode?: string | null
  production_message?: string | null
  caller_mode?: string | null
  caller_message?: string | null
}

export interface TestAgentTemplateInput {
  sections?: Array<{ key: string; title: string; content: string }>
  first_message?: TestAgentFirstMessageInput | null
}

export interface TestAgentTemplateDraft {
  sections: TestPromptSectionDraft[]
  first_message: TestAgentFirstMessageDraft
}

export interface ScenarioDraftItem {
  id: string
  name: string
  description: string
  goal?: string
  selected: boolean
}

export const PRODUCTION_FIRST_MESSAGE_OPTIONS: Array<{
  value: ProductionFirstMessageMode
  label: string
}> = [
  {
    value: 'assistant_speaks_first',
    label: 'Production agent speaks first (fixed greeting)',
  },
  {
    value: 'assistant_waits_for_user',
    label: 'Test caller speaks first (production agent waits)',
  },
  {
    value: 'assistant_speaks_first_model_generated',
    label: 'Production agent speaks first (AI-generated greeting)',
  },
]

export const DEFAULT_CALLER_MESSAGE = "Hello, I'm calling because I need some help."

const PRODUCTION_MODES = new Set<ProductionFirstMessageMode>([
  'assistant_speaks_first',
  'assistant_waits_for_user',
  'assistant_speaks_first_model_generated',
])

export function normalizeProductionMode(value?: string | null): ProductionFirstMessageMode {
  if (value && PRODUCTION_MODES.has(value as ProductionFirstMessageMode)) {
    return value as ProductionFirstMessageMode
  }
  return 'assistant_waits_for_user'
}

export function normalizeCallerMode(value?: string | null): CallerFirstMessageMode {
  return value === 'wait' ? 'wait' : 'speak_first'
}

export function deriveCallerFirstMessage(
  productionMode: ProductionFirstMessageMode | string,
  productionMessage?: string | null,
): TestAgentFirstMessageDraft {
  const mode = normalizeProductionMode(productionMode)
  if (mode === 'assistant_speaks_first' || mode === 'assistant_speaks_first_model_generated') {
    return {
      production_mode: mode,
      production_message:
        mode === 'assistant_speaks_first' ? productionMessage?.trim() || '' : null,
      caller_mode: 'wait',
      caller_message: null,
    }
  }

  return {
    production_mode: 'assistant_waits_for_user',
    production_message: null,
    caller_mode: 'speak_first',
    caller_message: DEFAULT_CALLER_MESSAGE,
  }
}

export function assembleTestAgentPrompt(sections: TestPromptSectionDraft[]): string {
  const byKey = Object.fromEntries(sections.map((section) => [section.key, section]))
  return CANONICAL_TEST_PROMPT_SECTIONS.map((canonical) => {
    const section = byKey[canonical.key]
    const title = section?.title.trim() || canonical.title
    const content = section?.content.trim() || 'Not specified in source prompt.'
    return `## ${title}\n\n${content}`
  }).join('\n\n')
}

export function emptyPromptSections(): TestPromptSectionDraft[] {
  return CANONICAL_TEST_PROMPT_SECTIONS.map((section) => ({
    key: section.key,
    title: section.title,
    content: '',
  }))
}

export function defaultTestAgentTemplate(): TestAgentTemplateDraft {
  return {
    sections: emptyPromptSections(),
    first_message: deriveCallerFirstMessage('assistant_waits_for_user'),
  }
}

export function templateFromApi(template?: TestAgentTemplateInput | null): TestAgentTemplateDraft {
  if (!template?.sections?.length) {
    return defaultTestAgentTemplate()
  }

  const byKey = Object.fromEntries(template.sections.map((section) => [section.key, section]))
  const sections = CANONICAL_TEST_PROMPT_SECTIONS.map((canonical) => {
    const section = byKey[canonical.key]
    return {
      key: canonical.key,
      title: section?.title?.trim() || canonical.title,
      content: section?.content?.trim() || '',
    }
  })

  const fm = template.first_message
  const productionMode = normalizeProductionMode(fm?.production_mode)
  const derived = deriveCallerFirstMessage(productionMode, fm?.production_message)

  return {
    sections,
    first_message: {
      production_mode: productionMode,
      production_message: fm?.production_message ?? derived.production_message,
      caller_mode: normalizeCallerMode(fm?.caller_mode ?? derived.caller_mode),
      caller_message: fm?.caller_message ?? derived.caller_message,
    },
  }
}

export function callerFirstMessageHelperText(firstMessage: TestAgentFirstMessageDraft): string {
  if (firstMessage.caller_mode === 'wait') {
    return 'Test caller will wait for the production agent to speak first.'
  }
  const opening = firstMessage.caller_message?.trim()
  return opening
    ? `Test caller will speak first: "${opening}"`
    : 'Test caller will speak first when the call connects.'
}

export function isTemplateFilled(template: TestAgentTemplateDraft): boolean {
  const wordCount = assembleTestAgentPrompt(template.sections)
    .trim()
    .split(/\s+/)
    .filter(Boolean).length
  return wordCount >= 10
}
