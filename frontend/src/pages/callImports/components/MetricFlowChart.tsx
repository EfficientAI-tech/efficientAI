import { useMemo, useEffect } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  type Edge,
  type Node,
  type NodeProps,
  MarkerType,
  useReactFlow,
  ReactFlowProvider,
} from '@xyflow/react'
import dagre from 'dagre'
import '@xyflow/react/dist/style.css'

import type { MetricFlowResponse } from '../../../types/api'

interface FlowNodeData extends Record<string, unknown> {
  label: string
  count: number
  isTerminal: boolean
  isStart: boolean
  mode: 'per_call' | 'aggregate'
}

const NODE_WIDTH = 180
const NODE_HEIGHT = 64

// Custom node renderer. We render a rounded card with the label + a
// dimmer "count" footer for aggregate mode. Terminal nodes get a thicker
// accent border so users can spot outcomes at a glance.
function FlowNode({ data }: NodeProps<Node<FlowNodeData>>) {
  const accent = data.isTerminal
    ? 'border-blue-500'
    : data.isStart
      ? 'border-gray-400 border-dashed'
      : 'border-gray-300'
  return (
    <div
      className={`rounded-md bg-white px-3 py-2 shadow-sm border-2 ${accent}`}
      style={{ width: NODE_WIDTH }}
    >
      <Handle type="target" position={Position.Left} className="opacity-0" />
      <div
        className={`text-xs font-semibold ${
          data.isStart ? 'text-gray-500' : 'text-gray-800'
        }`}
      >
        {data.label}
      </div>
      {data.mode === 'aggregate' && !data.isStart && (
        <div className="text-[10px] text-gray-500 mt-0.5">
          {data.count} {data.count === 1 ? 'call' : 'calls'}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="opacity-0" />
    </div>
  )
}

const nodeTypes = { flowNode: FlowNode }

function layoutWithDagre(
  nodes: Node<FlowNodeData>[],
  edges: Edge[],
): { nodes: Node<FlowNodeData>[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'LR', nodesep: 24, ranksep: 80 })

  nodes.forEach((n) => {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  })
  edges.forEach((e) => g.setEdge(e.source, e.target))

  dagre.layout(g)

  const positioned = nodes.map((n) => {
    const nodeWithPos = g.node(n.id)
    return {
      ...n,
      position: {
        x: nodeWithPos.x - NODE_WIDTH / 2,
        y: nodeWithPos.y - NODE_HEIGHT / 2,
      },
    }
  })

  return { nodes: positioned, edges }
}

interface MetricFlowChartProps {
  data: MetricFlowResponse
  mode?: 'per_call' | 'aggregate'
  height?: number
}

/**
 * Renders a React Flow diagram of the LLM-inferred call flow for a
 * parent metric.
 *
 * - ``aggregate`` mode (default) shows per-node call counts and edge
 *   thickness scaled by transition count across all rows.
 * - ``per_call`` mode is a single-row trace; counts are hidden and
 *   every edge is drawn at a uniform weight.
 *
 * The component is read-only: the user can pan/zoom but not drag
 * nodes or create edges. That keeps the visualisation strictly
 * synced to the LLM output.
 */
function MetricFlowChartInner({
  data,
  mode = 'aggregate',
  height = 360,
}: MetricFlowChartProps) {
  const { fitView } = useReactFlow()

  const totalForScale = useMemo(() => {
    if (mode === 'per_call') return 1
    return Math.max(1, data.rows_with_sequence || data.total_rows || 1)
  }, [data, mode])

  const { nodes, edges } = useMemo(() => {
    const initialNodes: Node<FlowNodeData>[] = data.nodes
      // Hide the START node in per_call mode — a single row only has
      // one path, so the explicit start is visual clutter.
      .filter((n) => mode !== 'per_call' || n.id !== '__START__')
      .map((n) => ({
        id: n.id,
        type: 'flowNode',
        position: { x: 0, y: 0 },
        data: {
          label: n.label,
          count: n.count,
          isTerminal: n.is_terminal,
          isStart: n.id === '__START__',
          mode,
        },
      }))

    const initialEdges: Edge[] = data.edges
      .filter((e) => mode !== 'per_call' || e.source !== '__START__')
      .map((e) => {
        const fraction = e.count / totalForScale
        const strokeWidth =
          mode === 'per_call'
            ? 2
            : Math.max(1.25, Math.min(8, 1.25 + fraction * 6))
        return {
          id: `${e.source}->${e.target}`,
          source: e.source,
          target: e.target,
          type: 'smoothstep',
          animated: false,
          style: { stroke: '#94a3b8', strokeWidth },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: '#94a3b8',
          },
          label: mode === 'aggregate' ? `${e.count}` : undefined,
          labelBgPadding: [4, 2] as [number, number],
          labelBgBorderRadius: 4,
          labelBgStyle: { fill: '#f8fafc', fillOpacity: 0.9 },
          labelStyle: { fontSize: 10, fill: '#475569' },
        }
      })

    return layoutWithDagre(initialNodes, initialEdges)
  }, [data, mode, totalForScale])

  // Auto-fit after the layout settles so the diagram never appears
  // zoomed off-screen on first render.
  useEffect(() => {
    const handle = setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 50)
    return () => clearTimeout(handle)
  }, [nodes, edges, fitView])

  return (
    <div className="border rounded-md bg-gray-50" style={{ height }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
        maxZoom={1.5}
      >
        <Background gap={16} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

export default function MetricFlowChart(props: MetricFlowChartProps) {
  // React Flow needs its provider to expose viewport state (used by
  // ``useReactFlow().fitView`` above) — wrap so callers can drop the
  // component anywhere without remembering this detail.
  return (
    <ReactFlowProvider>
      <MetricFlowChartInner {...props} />
    </ReactFlowProvider>
  )
}

/**
 * Build a single-row ``MetricFlowResponse`` from a parent metric's
 * ``metric_scores`` entry. The sequence array is converted into a
 * linear chain of nodes/edges so the same component can render both
 * per-call and aggregate diagrams without two code paths.
 */
export function flowFromSequence(
  parentMetricId: string,
  parentMetricName: string,
  sequence: string[],
  childIdByKey: Record<string, { id: string; name: string }>,
  selectionMode: 'single_choice' | 'multi_label' | null = null,
): MetricFlowResponse {
  const nodes: MetricFlowResponse['nodes'] = []
  const seenNodeIds = new Set<string>()
  const orderedIds: string[] = []

  for (const key of sequence) {
    const child = childIdByKey[key]
    if (!child) continue
    if (!seenNodeIds.has(child.id)) {
      seenNodeIds.add(child.id)
      nodes.push({
        id: child.id,
        label: child.name,
        count: 1,
        is_terminal: false,
      })
    }
    orderedIds.push(child.id)
  }
  if (orderedIds.length > 0) {
    nodes[nodes.length - 1].is_terminal = true
  }

  const edges: MetricFlowResponse['edges'] = []
  for (let i = 0; i < orderedIds.length - 1; i += 1) {
    if (orderedIds[i] === orderedIds[i + 1]) continue
    edges.push({ source: orderedIds[i], target: orderedIds[i + 1], count: 1 })
  }

  return {
    parent_metric_id: parentMetricId,
    parent_metric_name: parentMetricName,
    selection_mode: selectionMode,
    nodes,
    edges,
    total_rows: 1,
    rows_with_sequence: orderedIds.length > 0 ? 1 : 0,
  }
}
