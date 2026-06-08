import type { AgentFlowGraph, AgentFlowNode } from '../../types/api'

export function nodeHasValidMapping(node: AgentFlowNode, content: string): boolean {
  if (node.start_offset != null && node.end_offset != null) {
    const start = node.start_offset
    const end = node.end_offset
    if (end <= start || end > content.length) return false
    const span = content.slice(start, end)
    if (node.prompt_excerpt) return span === node.prompt_excerpt
    return true
  }
  if (node.prompt_excerpt) return content.includes(node.prompt_excerpt)
  return false
}

export function flowchartNeedsPromptMapping(
  flowchart: AgentFlowGraph | null | undefined,
  content: string,
): boolean {
  if (!flowchart?.nodes?.length) return false
  return flowchart.nodes.some((node) => !nodeHasValidMapping(node, content))
}

export function countMappedNodes(
  flowchart: AgentFlowGraph | null | undefined,
  content: string,
): number {
  if (!flowchart?.nodes?.length) return 0
  return flowchart.nodes.filter((node) => nodeHasValidMapping(node, content)).length
}
