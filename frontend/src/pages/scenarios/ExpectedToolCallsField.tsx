import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { apiClient } from '../../lib/api'
import type { ExpectedToolCall } from '../../types/api'

/** Suggested when the scenario has no agent yet; any tool name can be typed. */
const DEFAULT_TOOLS = ['search_knowledge_base']

type Mode = 'call' | 'succeed' | 'forbid'

function modeOf(call: ExpectedToolCall): Mode {
  if (call.forbidden) return 'forbid'
  return call.must_succeed ? 'succeed' : 'call'
}

function withMode(call: ExpectedToolCall, mode: Mode): ExpectedToolCall {
  return { ...call, forbidden: mode === 'forbid', must_succeed: mode === 'succeed' }
}

function mockText(value: unknown): string {
  if (value === undefined || value === null) return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

/** Mock tool output: JSON when it parses, otherwise sent as plain text. Committed on blur. */
function MockResponseInput({ value, onChange }: { value: unknown; onChange: (value: unknown) => void }) {
  const [text, setText] = useState(() => mockText(value))
  const commit = () => {
    if (!text.trim()) return onChange(undefined)
    try {
      onChange(JSON.parse(text))
    } catch {
      onChange(text)
    }
  }
  return (
    <textarea
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      rows={3}
      className="w-full rounded-lg border border-gray-300 px-2 py-1.5 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary-500"
      placeholder='Optional. Returned instead of running the tool, e.g. {"rows": [{"status": "shipped"}]}'
    />
  )
}

interface Props {
  value: ExpectedToolCall[]
  onChange: (value: ExpectedToolCall[]) => void
  /** Scenario's agent: its tool catalog feeds the tool-name suggestions. */
  agentId?: string | null
}

export default function ExpectedToolCallsField({ value, onChange, agentId }: Props) {
  const { data: catalog = [] } = useQuery({
    queryKey: ['agent-tool-catalog', agentId],
    queryFn: () => apiClient.getAgentToolCatalog(agentId as string),
    enabled: Boolean(agentId),
  })
  const toolNames = catalog.length ? catalog.map((entry) => entry.name) : DEFAULT_TOOLS
  const behaviorByTool = new Map(catalog.map((entry) => [entry.name, entry.simulation_behavior]))
  const update = (index: number, next: ExpectedToolCall) =>
    onChange(value.map((call, i) => (i === index ? next : call)))
  const remove = (index: number) => onChange(value.filter((_, i) => i !== index))

  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-gray-700">Expected tool calls</label>
      <p className="mb-2 text-xs text-gray-500">
        Checked on every simulation trial of this scenario. A trial only passes when all of them hold.
      </p>
      <datalist id="expected-tool-names">
        {toolNames.map((tool) => (
          <option key={tool} value={tool} />
        ))}
      </datalist>
      <div className="space-y-2">
        {value.map((call, index) => {
          const [argKey, argValue] = Object.entries(call.args_contains ?? {})[0] ?? ['', '']
          const mode = modeOf(call)
          return (
            <div key={index} className="space-y-2 rounded-lg border border-gray-200 p-3">
              <div className="flex items-center gap-2">
                <select
                  value={mode}
                  onChange={(e) => update(index, withMode(call, e.target.value as Mode))}
                  className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm"
                  aria-label="Expectation"
                >
                  <option value="call">Must call</option>
                  <option value="succeed">Must call successfully</option>
                  <option value="forbid">Must not call</option>
                </select>
                <input
                  list="expected-tool-names"
                  value={call.tool}
                  onChange={(e) => update(index, { ...call, tool: e.target.value })}
                  className="min-w-0 flex-1 rounded-lg border border-gray-300 px-2 py-1.5 font-mono text-sm"
                  placeholder="tool name"
                  aria-label="Tool name"
                />
                <button
                  type="button"
                  onClick={() => remove(index)}
                  className="text-gray-400 hover:text-red-600"
                  aria-label="Remove expected tool call"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-gray-600">
                <span>with argument</span>
                <input
                  value={argKey}
                  onChange={(e) =>
                    update(index, { ...call, args_contains: e.target.value ? { [e.target.value]: argValue } : {} })
                  }
                  className="w-24 rounded border border-gray-300 px-2 py-1 font-mono"
                  placeholder="query"
                  aria-label="Argument name"
                />
                <span>containing</span>
                <input
                  value={argValue}
                  onChange={(e) =>
                    update(index, { ...call, args_contains: argKey ? { [argKey]: e.target.value } : {} })
                  }
                  className="min-w-0 flex-1 rounded border border-gray-300 px-2 py-1"
                  placeholder="refund (optional)"
                  aria-label="Argument contains"
                />
                {mode !== 'forbid' ? (
                  <>
                    <span>at least</span>
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={call.min_calls ?? 1}
                      onChange={(e) => update(index, { ...call, min_calls: Math.max(1, Number(e.target.value) || 1) })}
                      className="w-14 rounded border border-gray-300 px-2 py-1 tabular-nums"
                      aria-label="Minimum calls"
                    />
                    <span>time(s)</span>
                  </>
                ) : null}
              </div>
              {agentId && call.tool && !behaviorByTool.has(call.tool) ? (
                <p className="text-xs text-amber-700">This agent has no tool named {call.tool}.</p>
              ) : behaviorByTool.get(call.tool) === 'mocked' ? (
                <p className="text-xs text-gray-500">Mocked in simulations, so it returns the response below or a fake success.</p>
              ) : null}
              {mode !== 'forbid' ? (
                <MockResponseInput
                  value={call.mock_response}
                  onChange={(mock_response) => update(index, { ...call, mock_response })}
                />
              ) : null}
            </div>
          )
        })}
      </div>
      <button
        type="button"
        onClick={() => onChange([...value, { tool: toolNames[0], min_calls: 1 }])}
        className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-primary-600 hover:underline"
      >
        <Plus className="h-4 w-4" /> Add expected tool call
      </button>
    </div>
  )
}
