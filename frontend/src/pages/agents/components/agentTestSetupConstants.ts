export const CANONICAL_TEST_PROMPT_SECTIONS = [
  { key: 'purpose', title: 'Purpose' },
  { key: 'behavior', title: 'Behavior' },
  { key: 'expected_interactions', title: 'Expected Interactions' },
  { key: 'personality_traits', title: 'Personality Traits' },
  { key: 'constraints', title: 'Constraints' },
] as const

export type TestPromptSectionKey = (typeof CANONICAL_TEST_PROMPT_SECTIONS)[number]['key']

export interface TestPromptSectionDraft {
  key: TestPromptSectionKey
  title: string
  content: string
}

export interface ScenarioDraftItem {
  id: string
  name: string
  description: string
  goal?: string
  selected: boolean
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
