import { useMemo, useState } from 'react'
import { Eye, Code } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import {
  CANONICAL_TEST_PROMPT_SECTIONS,
  PRODUCTION_FIRST_MESSAGE_OPTIONS,
  TestAgentFirstMessageDraft,
  TestAgentTemplateDraft,
  TestAgentTemplateInput,
  TestPromptSectionKey,
  assembleTestAgentPrompt,
  callerFirstMessageHelperText,
  deriveCallerFirstMessage,
  normalizeProductionMode,
  normalizeCallerMode,
} from './agentTestSetupConstants'

interface TestAgentTemplateEditorProps {
  template: TestAgentTemplateDraft
  onChange: (template: TestAgentTemplateDraft) => void
  legacyDescription?: string
  showLegacy?: boolean
  /** Expanded layout for agent workspace edit — taller editors, full-width. */
  variant?: 'default' | 'workspace'
}

function FirstMessageFields({
  firstMessage,
  onChange,
}: {
  firstMessage: TestAgentFirstMessageDraft
  onChange: (next: TestAgentFirstMessageDraft) => void
}) {
  const handleProductionModeChange = (productionMode: TestAgentFirstMessageDraft['production_mode']) => {
    onChange(deriveCallerFirstMessage(productionMode, firstMessage.production_message))
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label htmlFor="first-message-mode" className="text-sm font-medium text-gray-700">
          Who speaks first on the call?
        </label>
        <select
          id="first-message-mode"
          value={firstMessage.production_mode}
          onChange={(e) =>
            handleProductionModeChange(e.target.value as TestAgentFirstMessageDraft['production_mode'])
          }
          className="min-w-[16rem] max-w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white"
        >
          {PRODUCTION_FIRST_MESSAGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {firstMessage.production_mode === 'assistant_speaks_first' ? (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Production agent greeting (mirror)
          </label>
          <textarea
            value={firstMessage.production_message || ''}
            onChange={(e) =>
              onChange({
                ...firstMessage,
                production_message: e.target.value,
              })
            }
            rows={3}
            placeholder="Thank you for calling Wellness Partners. This is Riley, your scheduling assistant…"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
          />
        </div>
      ) : null}

      {firstMessage.caller_mode === 'speak_first' ? (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Test caller opening line
          </label>
          <textarea
            value={firstMessage.caller_message || ''}
            onChange={(e) =>
              onChange({
                ...firstMessage,
                caller_message: e.target.value,
              })
            }
            rows={2}
            placeholder="Hello, I'm calling because I need some help."
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
          />
        </div>
      ) : null}

      <p className="text-xs text-gray-600">{callerFirstMessageHelperText(firstMessage)}</p>
    </div>
  )
}

export default function TestAgentTemplateEditor({
  template,
  onChange,
  legacyDescription,
  showLegacy = false,
  variant = 'default',
}: TestAgentTemplateEditorProps) {
  const [activeSection, setActiveSection] = useState<TestPromptSectionKey>('complementary_goal')
  const [viewMode, setViewMode] = useState<'edit' | 'preview'>('edit')
  const isWorkspace = variant === 'workspace'

  const assembledPrompt = useMemo(() => assembleTestAgentPrompt(template.sections), [template.sections])
  const activeSectionDraft = template.sections.find((section) => section.key === activeSection)

  const sectionEditorMinHeight = isWorkspace
    ? 'min-h-[min(520px,calc(100vh-22rem))]'
    : 'min-h-[220px]'
  const previewMaxHeight = isWorkspace
    ? 'max-h-[min(640px,calc(100vh-16rem))]'
    : 'max-h-[320px]'

  const updateSection = (key: TestPromptSectionKey, content: string) => {
    onChange({
      ...template,
      sections: template.sections.map((section) =>
        section.key === key ? { ...section, content } : section,
      ),
    })
  }

  const updateFirstMessage = (next: TestAgentFirstMessageDraft) => {
    onChange({ ...template, first_message: next })
  }

  return (
    <div className={`space-y-6 ${isWorkspace ? 'w-full' : ''}`}>
      {showLegacy && legacyDescription?.trim() ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-medium text-amber-900 mb-1">Legacy prompt</p>
          <p className="text-xs text-amber-800">
            This agent uses a free-form prompt from before structured templates. Regenerate from
            production to populate sections, or edit sections below.
          </p>
        </div>
      ) : null}

      <section className="rounded-lg border border-indigo-200 bg-indigo-50/40 overflow-hidden">
        <div className="border-b border-indigo-100 bg-indigo-50/80 px-4 py-3">
          <h3 className="text-sm font-semibold text-gray-900">First message</h3>
          <p className="text-xs text-gray-600 mt-0.5">
            Whether the production agent or the simulated test caller opens the call — separate from
            the caller system prompt below.
          </p>
        </div>
        <div className="p-4 bg-white/60">
          <FirstMessageFields
            firstMessage={template.first_message}
            onChange={updateFirstMessage}
          />
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 bg-white overflow-hidden">
        <div className="border-b border-gray-200 bg-gray-50 px-4 py-3">
          <h3 className="text-sm font-semibold text-gray-900">System prompt</h3>
          <p className="text-xs text-gray-600 mt-0.5">
            Caller persona and scenario behavior — assembled into the live test agent prompt.
          </p>
        </div>

        <div className="flex flex-wrap gap-1 border-b border-gray-200 bg-gray-50 px-2 py-2">
          {CANONICAL_TEST_PROMPT_SECTIONS.map((section) => (
            <button
              key={section.key}
              type="button"
              onClick={() => setActiveSection(section.key)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                activeSection === section.key
                  ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {section.title}
            </button>
          ))}
        </div>

        <div className="p-4">
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-gray-700">
              {activeSectionDraft?.title || 'Section'}
            </label>
            <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
              <button
                type="button"
                onClick={() => setViewMode('edit')}
                className={`inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md ${
                  viewMode === 'edit' ? 'bg-white shadow-sm' : 'text-gray-500'
                }`}
              >
                <Code className="h-3 w-3" />
                Edit
              </button>
              <button
                type="button"
                onClick={() => setViewMode('preview')}
                className={`inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md ${
                  viewMode === 'preview' ? 'bg-white shadow-sm' : 'text-gray-500'
                }`}
              >
                <Eye className="h-3 w-3" />
                Preview
              </button>
            </div>
          </div>

          {viewMode === 'edit' ? (
            <textarea
              value={activeSectionDraft?.content || ''}
              onChange={(e) => updateSection(activeSection, e.target.value)}
              placeholder={`Describe ${activeSectionDraft?.title.toLowerCase()}…`}
              className={`w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 font-mono text-sm resize-y ${sectionEditorMinHeight}`}
            />
          ) : (
            <div
              className={`border border-gray-200 rounded-lg p-3 prose prose-sm max-w-none bg-gray-50 overflow-y-auto ${sectionEditorMinHeight}`}
            >
              {activeSectionDraft?.content?.trim() ? (
                <ReactMarkdown>{activeSectionDraft.content}</ReactMarkdown>
              ) : (
                <p className="text-gray-400 italic">Nothing in this section yet.</p>
              )}
            </div>
          )}
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 bg-gray-50 overflow-hidden">
        <div className="border-b border-gray-200 px-4 py-3 bg-white">
          <label className="text-sm font-medium text-gray-700">Assembled system prompt</label>
          <p className="text-xs text-gray-500 mt-0.5">Full preview of all sections combined.</p>
        </div>
        <div className={`overflow-y-auto p-4 prose prose-sm max-w-none ${previewMaxHeight}`}>
          {assembledPrompt.trim() ? (
            <ReactMarkdown>{assembledPrompt}</ReactMarkdown>
          ) : (
            <p className="text-gray-400 italic">Fill in sections to preview the assembled prompt.</p>
          )}
        </div>
      </section>
    </div>
  )
}

export function applyGeneratedTemplate(
  current: TestAgentTemplateDraft,
  generated: TestAgentTemplateInput & { test_agent_template?: TestAgentTemplateInput },
): TestAgentTemplateDraft {
  const payload = generated.test_agent_template || generated
  const sections = (payload.sections || []).map((section) => ({
    key: section.key as TestPromptSectionKey,
    title: section.title,
    content: section.content,
  }))

  const productionMode = normalizeProductionMode(payload.first_message?.production_mode)
  const derived = deriveCallerFirstMessage(
    productionMode,
    payload.first_message?.production_message,
  )

  return {
    sections: sections.length
      ? CANONICAL_TEST_PROMPT_SECTIONS.map((canonical) => {
          const match = sections.find((section) => section.key === canonical.key)
          return {
            key: canonical.key,
            title: match?.title || canonical.title,
            content: match?.content || '',
          }
        })
      : current.sections,
    first_message: {
      production_mode: productionMode,
      production_message:
        payload.first_message?.production_message ?? derived.production_message,
      caller_mode: normalizeCallerMode(
        payload.first_message?.caller_mode ?? derived.caller_mode,
      ),
      caller_message: payload.first_message?.caller_message ?? derived.caller_message,
    },
  }
}
