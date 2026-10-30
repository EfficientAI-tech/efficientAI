import { callToFlowGraph, evidenceNodeId } from './callFlow'
import type { MockCall } from './mockCalls'
import type { AgentFlowGraph } from '../../../types/api'

type FlowNodeType = AgentFlowGraph['nodes'][number]['node_type']

const FLOW_SECTIONS: Array<{
  label: string
  match: (nodeType: FlowNodeType) => boolean
}> = [
  { label: 'Conversation', match: (type) => type === 'start' || type === 'action' },
  { label: 'Tools & retrieval', match: (type) => type === 'decision' },
  { label: 'Outcome', match: (type) => type === 'terminal' },
]

export default function CallFlowStrip({
  call,
  metricId,
}: {
  call: MockCall
  metricId: string
}) {
  const graph = callToFlowGraph(call, metricId)
  const highlight = evidenceNodeId(call, metricId)
  const sections = FLOW_SECTIONS.map((section) => ({
    ...section,
    nodes: graph.nodes.filter((node) => section.match(node.node_type)),
  })).filter((section) => section.nodes.length > 0)

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-3">
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-gray-500">Call flow</p>
      <div className="space-y-3">
        {sections.map((section) => (
          <div key={section.label}>
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">{section.label}</p>
            <div className="flex flex-wrap items-center gap-1.5">
              {section.nodes.map((node, index) => (
                <span key={node.id} className="inline-flex items-center gap-1.5">
                  {index > 0 && <span className="text-gray-300">→</span>}
                  <span
                    className={`max-w-[160px] truncate rounded-full border px-2 py-0.5 text-[11px] ${
                      node.id === highlight
                        ? 'border-indigo-400 bg-indigo-50 text-indigo-900'
                        : node.node_type === 'terminal'
                          ? 'border-blue-200 bg-blue-50 text-blue-900'
                          : node.node_type === 'decision'
                            ? 'border-amber-200 bg-amber-50 text-amber-900'
                            : 'border-gray-200 bg-gray-50 text-gray-700'
                    }`}
                    title={node.label}
                  >
                    {node.label}
                  </span>
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
