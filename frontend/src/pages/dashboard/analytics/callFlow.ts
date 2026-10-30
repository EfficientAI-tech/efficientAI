import type { AgentFlowGraph } from '../../../types/api'
import type { MockCall } from './mockCalls'

function clip(text: string, max = 42): string {
  const trimmed = text.replace(/\s+/g, ' ').trim()
  return trimmed.length <= max ? trimmed : `${trimmed.slice(0, max - 1)}…`
}

export function callToFlowGraph(call: MockCall, metricId?: string | null): AgentFlowGraph {
  const evidence = new Set(metricId ? (call.metric_scores[metricId]?.evidenceTurnIndexes ?? []) : [])
  const nodes: AgentFlowGraph['nodes'] = [{ id: 'start', label: 'Start', node_type: 'start' }]
  const edges: AgentFlowGraph['edges'] = []
  let prev = 'start'

  call.turns.forEach((turn, index) => {
    const id = `t${index}`
    let nodeType: AgentFlowGraph['nodes'][number]['node_type'] = 'action'
    let label = turn.speaker === 'human' ? `Caller: ${clip(turn.text)}` : clip(turn.text)
    if (turn.toolCall) {
      nodeType = 'decision'
      label = `${turn.toolCall.name}${turn.toolCall.failed ? ' failed' : ''}`
    } else if (turn.ragCall) {
      nodeType = 'decision'
      label = `RAG${turn.ragCall.failed ? ' failed' : ''}`
    }
    nodes.push({
      id,
      label,
      node_type: nodeType,
      prompt_excerpt: evidence.has(index) ? 'evidence' : null,
    })
    edges.push({ source: prev, target: id })
    prev = id
  })

  nodes.push({
    id: 'end',
    label: call.endedReason ?? (call.endedEarly ? 'ended early' : 'completed'),
    node_type: 'terminal',
  })
  edges.push({ source: prev, target: 'end' })
  return { nodes, edges }
}

export function evidenceNodeId(call: MockCall, metricId?: string | null): string | null {
  const index = metricId ? call.metric_scores[metricId]?.evidenceTurnIndexes[0] : undefined
  return index == null ? null : `t${index}`
}
