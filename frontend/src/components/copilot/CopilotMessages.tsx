import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { AlertTriangle, ArrowRight, Check, ChevronDown, ChevronRight, Copy, Loader2, X } from 'lucide-react'
import type { CopilotAction, CopilotMessage, CopilotToolCall, CopilotWizardCard, TestSetupDraft } from '../../lib/copilotApi'
import { ProposalCard } from './ProposalCard'
import { copyTextToClipboard } from '../../lib/clipboard'

const TOOL_LABELS: Record<string, string> = {
  list_agents: 'Looked up agents',
  get_agent: 'Read agent details',
  list_personas: 'Looked up personas',
  list_scenarios: 'Looked up scenarios',
  list_evaluators: 'Looked up evaluators',
  list_metrics: 'Looked up metrics',
  get_evaluation_activity: 'Checked evaluation activity',
  generate_test_setup: 'Drafted a test setup',
  search_docs: 'Searched the docs',
  list_imports: 'Looked up imports',
  get_import: 'Read an import',
  get_import_upload: 'Read the uploaded file',
  get_import_evaluation_results: 'Read evaluation results',
  get_failure_clusters: 'Read failure clusters',
  get_import_insights: 'Read insights',
  search_import_rows: 'Searched calls',
  get_prompt_suggestions: 'Read prompt suggestions',
  get_metric_trend: 'Analysed a metric',
  compare_metrics: 'Compared metrics',
  get_production_calls: 'Checked production calls',
  list_simulation_runs: 'Looked up simulation runs',
  get_simulation_run: 'Read a simulation run',
  list_evaluation_suites: 'Looked up evaluation suites',
  open_create_agent_wizard: 'Prepared the agent wizard',
}

function toolLabel(name: string): string {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name]
  if (name.startsWith('propose_')) return `Proposed: ${name.slice(8).replace(/_/g, ' ')}`
  return name.replace(/_/g, ' ')
}

function ToolChip({ call }: { call: CopilotToolCall }) {
  const label = toolLabel(call.name)
  const icon =
    call.status === 'running' ? (
      <Loader2 className="h-3 w-3 animate-spin" />
    ) : call.status === 'ok' ? (
      <Check className="h-3 w-3 text-emerald-600" />
    ) : (
      <X className="h-3 w-3 text-red-500" />
    )
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-xs text-gray-600">
      {icon}
      {call.status === 'running' ? `${label}…` : label}
    </span>
  )
}

function DraftCard({ draft }: { draft: TestSetupDraft }) {
  const [open, setOpen] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  return (
    <div className="mt-2 rounded-lg border border-gray-200 bg-white text-sm">
      <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
        <div className="font-medium text-gray-900">Test setup draft · {draft.agent_name}</div>
        <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">Not saved</span>
      </div>
      <div className="divide-y divide-gray-100">
        {draft.sections.map((section) => (
          <div key={section.key}>
            <button
              type="button"
              className="flex w-full items-center gap-1 px-3 py-1.5 text-left text-gray-700 hover:bg-gray-50"
              onClick={() => setOpen(open === section.key ? null : section.key)}
            >
              {open === section.key ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              {section.title}
            </button>
            {open === section.key && (
              <p className="whitespace-pre-wrap px-3 pb-2 text-xs text-gray-600">{section.content}</p>
            )}
          </div>
        ))}
      </div>
      {draft.scenarios.length > 0 && (
        <div className="border-t border-gray-100 px-3 py-2">
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-500">
            Scenarios ({draft.scenarios.length})
          </div>
          <ul className="space-y-1">
            {draft.scenarios.map((s, i) => (
              <li key={i} className="text-xs text-gray-700">
                <span className="font-medium">{s.name}</span>
                {s.description ? <span className="text-gray-500"> — {s.description}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex justify-end border-t border-gray-100 px-3 py-2">
        <button
          type="button"
          className="inline-flex items-center gap-1 text-xs text-gray-600 hover:text-gray-900"
          onClick={() =>
            copyTextToClipboard(draft.test_agent_prompt, () => {
              setCopied(true)
              window.setTimeout(() => setCopied(false), 1500)
            })
          }
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? 'Copied' : 'Copy test prompt'}
        </button>
      </div>
    </div>
  )
}

function WizardCard({ wizard }: { wizard: CopilotWizardCard['wizard'] }) {
  const navigate = useNavigate()
  return (
    <div className="mt-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm">
      <div className="font-medium text-gray-900">New {wizard.call_medium} agent · {wizard.name}</div>
      <p className="mt-0.5 text-xs text-gray-600">
        Opens the create-agent form pre-filled{wizard.production_prompt ? ' with the prompt' : ''}. Connections and
        numbers are set up there.
      </p>
      <button
        type="button"
        className="mt-2 inline-flex items-center gap-1 rounded-md bg-gray-900 px-2 py-1 text-xs text-white hover:bg-gray-800"
        onClick={() =>
          navigate('/agents', {
            state: {
              copilotCreateAgent: {
                name: wizard.name,
                call_medium: wizard.call_medium,
                production_prompt: wizard.production_prompt,
                description: wizard.description,
              },
            },
          })
        }
      >
        Open in agent wizard <ArrowRight className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

function Markdown({ text }: { text: string }) {
  return (
    <div className="prose prose-sm max-w-none prose-p:my-1.5 prose-ul:my-1.5 prose-table:text-xs">
      <ReactMarkdown
        components={{
          // Tool links are app-relative: navigate in-app. Anything else opens a new tab.
          a: ({ href, children }) =>
            href && href.startsWith('/') && !href.startsWith('//') ? (
              <Link to={href}>{children}</Link>
            ) : (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

const STATUS_NOTES: Partial<Record<CopilotMessage['status'], string>> = {
  cancelled: 'Stopped.',
  interrupted: 'This reply was interrupted. Ask again to retry.',
}

export function CopilotMessageView({
  message,
  actions,
  onActionChanged,
}: {
  message: CopilotMessage
  actions: Record<string, CopilotAction>
  onActionChanged: (action: CopilotAction) => void
}) {
  if (message.role === 'event') {
    return <div className="px-2 text-center text-[11px] text-gray-400">{message.content}</div>
  }
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-gray-900 px-3 py-2 text-sm text-white">
          {message.content}
        </div>
      </div>
    )
  }
  const cards = message.tool_calls.filter((c) => c.ui)
  const thinking = message.status === 'streaming' && !message.content && !message.tool_calls.length
  return (
    <div className="space-y-1.5">
      {message.tool_calls.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {message.tool_calls.map((call) => (
            <ToolChip key={call.id} call={call} />
          ))}
        </div>
      )}
      {thinking && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Thinking…
        </div>
      )}
      {message.content && <Markdown text={message.content} />}
      {cards.map((call) => {
        const ui = call.ui
        if (ui?.type === 'draft') return <DraftCard key={call.id} draft={ui.draft} />
        if (ui?.type === 'wizard') return <WizardCard key={call.id} wizard={ui.wizard} />
        if (ui?.type === 'proposal') {
          return (
            <ProposalCard key={call.id} action={actions[ui.action.id] ?? ui.action} onChanged={onActionChanged} />
          )
        }
        return null
      })}
      {message.error && message.status !== 'cancelled' && (
        <div className="flex items-start gap-1.5 rounded-md bg-red-50 px-2 py-1.5 text-xs text-red-700">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
          {message.error}
        </div>
      )}
      {STATUS_NOTES[message.status] && <div className="text-xs text-gray-400">{STATUS_NOTES[message.status]}</div>}
    </div>
  )
}
