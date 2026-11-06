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
              {(toolCallsByTurn?.get(idx) ?? []).map((call, callIdx) => (
                <div key={call.call_id ?? callIdx} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                  <div className="max-w-[85%]">
                    <ToolCallCard call={call} />
                  </div>
                </div>
              ))}
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
