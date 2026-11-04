import { ChevronRight, Wrench } from 'lucide-react'
import { transcriptBubbleClass, transcriptMetaClass } from '../../components/call-recordings/transcriptBubbleStyles'
import type { SimulationToolCall } from '../../types/api'
import { ToolCallCard } from './ToolCallCard'

export type ChatSimulationTurn = {
  role: 'agent' | 'user' | string
  text: string
  latencyMs?: number
}

function isTestAgentTurn(role: string): boolean {
  const r = role.trim().toLowerCase()
  return r === 'user' || r === 'test' || r === 'customer' || r === 'speaker 1'
}

function turnLabel(role: string, agentName: string, personaName: string): string {
  if (isTestAgentTurn(role)) return personaName.trim() || 'Test agent'
  return agentName.trim() || 'Production agent'
}

function toolGroupSummary(calls: SimulationToolCall[]): string {
  const failed = calls.filter((c) => c.status === 'error').length
  const mocked = calls.filter((c) => c.status === 'mocked').length
  const seconds = calls.reduce((total, c) => total + (c.latency_ms || 0), 0) / 1000
  const parts = [`${seconds.toFixed(1)}s`]
  if (failed) parts.push(`${failed} failed`)
  if (mocked) parts.push(`${mocked} mocked`)
  return parts.join(' · ')
}

/** Tool calls the agent made before one reply, collapsed into a single row until opened. */
function ToolCallGroup({ calls, alignEnd }: { calls: SimulationToolCall[]; alignEnd: boolean }) {
  const failed = calls.some((c) => c.status === 'error')
  const tools = Array.from(new Set(calls.map((c) => c.tool)))
  return (
    <div className={`flex ${alignEnd ? 'justify-end' : 'justify-start'}`}>
      <details className="group w-full max-w-[85%] rounded-lg border border-dashed border-gray-300 bg-gray-50 text-xs">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-1.5 [&::-webkit-details-marker]:hidden">
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-gray-400 transition-transform group-open:rotate-90" />
          <Wrench className="h-3.5 w-3.5 shrink-0 text-gray-400" />
          <span className="font-medium text-gray-700">
            {calls.length} {calls.length === 1 ? 'tool call' : 'tool calls'}
          </span>
          <span className="truncate font-mono text-gray-500">{tools.join(', ')}</span>
          <span className={`ml-auto shrink-0 tabular-nums ${failed ? 'text-red-700' : 'text-gray-500'}`}>
            {toolGroupSummary(calls)}
          </span>
        </summary>
        <div className="space-y-1.5 border-t border-gray-200 p-2">
          {calls.map((call, callIdx) => (
            <ToolCallCard key={call.call_id ?? callIdx} call={call} />
          ))}
        </div>
      </details>
    </div>
  )
}

type Props = {
  turns: ChatSimulationTurn[]
  agentName?: string
  personaName?: string
  toolCallsByTurn?: Map<number, SimulationToolCall[]>
}

/** Chat-style transcript matching evaluation result drawers (indigo caller, gray agent). */
export default function ChatSimulationTranscript({
  turns,
  agentName = 'Production agent',
  personaName = 'Test agent',
  toolCallsByTurn,
}: Props) {
  if (turns.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-500">No conversation recorded.</p>
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="space-y-3 pr-1">
        {turns.map((turn, idx) => {
          const isUser = isTestAgentTurn(turn.role)
          const timing =
            turn.latencyMs !== undefined ? `${(turn.latencyMs / 1000).toFixed(1)}s` : null
          return (
            <div key={idx} className="space-y-1.5">
              {toolCallsByTurn?.get(idx)?.length ? (
                <ToolCallGroup calls={toolCallsByTurn.get(idx)!} alignEnd={isUser} />
              ) : null}
              <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                <div className={transcriptBubbleClass(isUser)}>
                  <div className={transcriptMetaClass(isUser)}>
                    <span>{turnLabel(turn.role, agentName, personaName)}</span>
                    {timing ? (
                      <span className="font-normal normal-case tracking-normal tabular-nums">{timing}</span>
                    ) : null}
                  </div>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{turn.text}</p>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
