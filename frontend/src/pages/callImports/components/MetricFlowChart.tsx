import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
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
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
} from '@xyflow/react'
import dagre from 'dagre'
import { Maximize2, Minimize2, RotateCcw } from 'lucide-react'
import '@xyflow/react/dist/style.css'

import type { MetricFlowResponse } from '../../../types/api'

interface FlowNodeData extends Record<string, unknown> {
  label: string
  count: number
  isTerminal: boolean
  isStart: boolean
  isDiscovered: boolean
  mode: 'per_call' | 'aggregate'
}

const NODE_WIDTH = 180
const NODE_HEIGHT = 64

// Custom node renderer. We render a rounded card with the label + a
// dimmer "count" footer for aggregate mode. Terminal nodes get a thicker
// accent border so users can spot outcomes at a glance. Discovered
// nodes — labels the LLM proposed instead of ones the user defined —
// get a dashed amber border + a small "discovered" pill so the user
// can spot promotion candidates at a glance.
function FlowNode({ data }: NodeProps<Node<FlowNodeData>>) {
  let accent: string
  if (data.isDiscovered) {
    accent = 'border-amber-500 border-dashed'
  } else if (data.isTerminal) {
    accent = 'border-blue-500'
  } else if (data.isStart) {
    accent = 'border-gray-400 border-dashed'
  } else {
    accent = 'border-gray-300'
  }
  return (
    <div
      className={`rounded-md bg-white px-3 py-2 shadow-sm border-2 ${accent}`}
      style={{ width: NODE_WIDTH }}
    >
      <Handle type="target" position={Position.Left} className="opacity-0" />
      <div className="flex items-start justify-between gap-1">
        <div
          className={`text-xs font-semibold ${
            data.isStart ? 'text-gray-500' : 'text-gray-800'
          }`}
        >
          {data.label}
        </div>
        {data.isDiscovered && (
          <span
            className="text-[9px] uppercase tracking-wide font-semibold rounded-sm bg-amber-50 text-amber-700 border border-amber-200 px-1 py-[1px]"
            title="LLM-discovered candidate (click Promote in the Discovered Metrics panel to make it a real sub-metric)"
          >
            discovered
          </span>
        )}
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
  // Slightly more generous ranksep + edgesep so the smoothstep edges
  // have room to bend around node corners — reduces visual overlap
  // between connectors and node labels in dense graphs. Users can
  // still hand-position individual nodes when ``nodesDraggable`` is
  // enabled (see chart toolbar).
  g.setGraph({
    rankdir: 'LR',
    nodesep: 36,
    ranksep: 110,
    edgesep: 24,
  })

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

/** Lightweight payload describing a clicked node in the flow chart. */
export interface FlowNodeClick {
  id: string
  label: string
  isStart: boolean
  isDiscovered: boolean
  isTerminal: boolean
}

/** Lightweight payload describing a clicked edge in the flow chart. */
export interface FlowEdgeClick {
  source: FlowNodeClick
  target: FlowNodeClick
}

interface MetricFlowChartProps {
  data: MetricFlowResponse
  mode?: 'per_call' | 'aggregate'
  height?: number
  /**
   * Fired when the user clicks a node in the diagram. In aggregate mode
   * the parent uses this to filter the row table to calls whose sequence
   * contains that label; the click is a no-op when omitted.
   */
  onNodeClick?: (node: FlowNodeClick) => void
  /**
   * Fired when the user clicks an edge in the diagram. Useful for
   * "show me every call where A is followed by B" drilldowns. Omit to
   * disable edge clicks entirely.
   */
  onEdgeClick?: (edge: FlowEdgeClick) => void
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
 * In aggregate mode the user can drag individual nodes to disambiguate
 * dense layouts. A "Reset layout" button re-runs dagre to undo any
 * manual tweaks. A "Fullscreen" toggle pops the chart into a
 * viewport-sized overlay (via React portal) for big graphs.
 */
function MetricFlowChartInner({
  data,
  mode = 'aggregate',
  height = 360,
  onNodeClick,
  onEdgeClick,
  isFullscreen,
  onToggleFullscreen,
}: MetricFlowChartProps & {
  isFullscreen?: boolean
  onToggleFullscreen?: () => void
}) {
  const { fitView } = useReactFlow()

  const totalForScale = useMemo(() => {
    if (mode === 'per_call') return 1
    return Math.max(1, data.rows_with_sequence || data.total_rows || 1)
  }, [data, mode])

  // Compute the laid-out nodes/edges from props. We then push them into
  // ``useNodesState`` so the user can drag individual nodes around;
  // dagre re-runs only on Reset Layout or when the underlying ``data``
  // changes (e.g. a new evaluation row finishes scoring).
  const initialLayout = useMemo(() => {
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
          isDiscovered: Boolean(n.is_discovered),
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

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<FlowNodeData>>(
    initialLayout.nodes,
  )
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(
    initialLayout.edges,
  )

  // Re-seed React Flow's internal state whenever the upstream data /
  // layout changes. Without this, a later evaluation row finishing
  // would be silently ignored because we'd still be rendering the
  // first snapshot.
  useEffect(() => {
    setNodes(initialLayout.nodes)
    setEdges(initialLayout.edges)
  }, [initialLayout, setNodes, setEdges])

  // Auto-fit after the layout settles so the diagram never appears
  // zoomed off-screen on first render or on fullscreen toggle.
  useEffect(() => {
    const handle = setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 50)
    return () => clearTimeout(handle)
  }, [initialLayout, isFullscreen, fitView])

  const resetLayout = useCallback(() => {
    setNodes(initialLayout.nodes)
    setEdges(initialLayout.edges)
    setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 30)
  }, [initialLayout, setNodes, setEdges, fitView])

  const handleNodeClick = onNodeClick
    ? (_: unknown, node: Node<FlowNodeData>) => {
        if (node.data.isStart) return
        onNodeClick({
          id: node.id,
          label: node.data.label,
          isStart: node.data.isStart,
          isDiscovered: node.data.isDiscovered,
          isTerminal: node.data.isTerminal,
        })
      }
    : undefined

  const handleEdgeClick = onEdgeClick
    ? (_: unknown, edge: Edge) => {
        const sourceNode = nodes.find((n) => n.id === edge.source)
        const targetNode = nodes.find((n) => n.id === edge.target)
        if (!sourceNode || !targetNode) return
        // Skip START-anchored edges — clicking them would be
        // equivalent to "all rows" since every sequence starts there.
        if (sourceNode.data.isStart) return
        onEdgeClick({
          source: {
            id: sourceNode.id,
            label: sourceNode.data.label,
            isStart: sourceNode.data.isStart,
            isDiscovered: sourceNode.data.isDiscovered,
            isTerminal: sourceNode.data.isTerminal,
          },
          target: {
            id: targetNode.id,
            label: targetNode.data.label,
            isStart: targetNode.data.isStart,
            isDiscovered: targetNode.data.isDiscovered,
            isTerminal: targetNode.data.isTerminal,
          },
        })
      }
    : undefined

  // Click is only meaningful in aggregate mode (per_call shows a single
  // row, so filtering wouldn't change anything). We still gate via the
  // handlers above so callers can opt in.
  const interactionsEnabled =
    mode === 'aggregate' && (onNodeClick || onEdgeClick)
  const draggable = mode === 'aggregate'

  return (
    <div
      className={
        isFullscreen
          ? 'flex flex-col h-full bg-gray-50'
          : 'border rounded-md bg-gray-50 relative flex flex-col'
      }
      style={isFullscreen ? undefined : { height }}
    >
      {/* Toolbar: Reset layout + Fullscreen toggle. Lives inside the
          chart container so it works in both inline and fullscreen
          renderings without a duplicated component. */}
      {(draggable || onToggleFullscreen) && (
        <div className="absolute top-2 right-2 z-10 flex items-center gap-1.5 bg-white/90 backdrop-blur border border-gray-200 rounded-md shadow-sm p-1">
          {draggable && (
            <button
              type="button"
              onClick={resetLayout}
              title="Reset chart layout (re-runs auto-arrange)"
              className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium text-gray-700 hover:text-gray-900 hover:bg-gray-100 rounded"
            >
              <RotateCcw className="h-3 w-3" /> Reset
            </button>
          )}
          {onToggleFullscreen && (
            <button
              type="button"
              onClick={onToggleFullscreen}
              title={
                isFullscreen
                  ? 'Exit fullscreen (Esc)'
                  : 'Open fullscreen view'
              }
              className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium text-gray-700 hover:text-gray-900 hover:bg-gray-100 rounded"
            >
              {isFullscreen ? (
                <>
                  <Minimize2 className="h-3 w-3" /> Exit
                </>
              ) : (
                <>
                  <Maximize2 className="h-3 w-3" /> Fullscreen
                </>
              )}
            </button>
          )}
        </div>
      )}
      <div className="flex-1 min-h-0">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={draggable ? onNodesChange : undefined}
          onEdgesChange={onEdgesChange}
          fitView
          nodesDraggable={draggable}
          nodesConnectable={false}
          edgesFocusable={Boolean(handleEdgeClick && mode === 'aggregate')}
          elementsSelectable={Boolean(interactionsEnabled || draggable)}
          onNodeClick={mode === 'aggregate' ? handleNodeClick : undefined}
          onEdgeClick={mode === 'aggregate' ? handleEdgeClick : undefined}
          proOptions={{ hideAttribution: true }}
          minZoom={0.2}
          maxZoom={1.5}
        >
          <Background gap={16} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  )
}

export default function MetricFlowChart(props: MetricFlowChartProps) {
  // Local fullscreen state lives at this layer so callers don't have
  // to thread it; the ``aggregate`` mode also gets a toolbar with a
  // Reset button (per-call mode hides both since it's a single trace).
  const [isFullscreen, setIsFullscreen] = useState(false)
  const allowFullscreen = (props.mode ?? 'aggregate') === 'aggregate'

  // ESC closes fullscreen so users have a keyboard escape hatch
  // alongside the toolbar's Exit button.
  useEffect(() => {
    if (!isFullscreen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsFullscreen(false)
    }
    window.addEventListener('keydown', handler)
    // Lock body scroll while the overlay is open so the page behind
    // doesn't scroll when the user pans the chart.
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', handler)
      document.body.style.overflow = prevOverflow
    }
  }, [isFullscreen])

  // React Flow needs its provider to expose viewport state (used by
  // ``useReactFlow().fitView``) — wrap so callers can drop the
  // component anywhere without remembering this detail.
  if (isFullscreen && allowFullscreen) {
    return createPortal(
      <div className="fixed inset-0 z-50 bg-white flex flex-col">
        <div className="border-b border-gray-200 px-4 py-2 flex items-center justify-between bg-gray-50">
          <p className="text-sm font-semibold text-gray-900">
            {props.data.parent_metric_name} · Flow
          </p>
          <p className="text-[11px] text-gray-500">
            Drag nodes to fix overlaps · Esc to close
          </p>
        </div>
        <div className="flex-1 min-h-0">
          <ReactFlowProvider>
            <MetricFlowChartInner
              {...props}
              isFullscreen
              onToggleFullscreen={() => setIsFullscreen(false)}
            />
          </ReactFlowProvider>
        </div>
      </div>,
      document.body,
    )
  }

  return (
    <ReactFlowProvider>
      <MetricFlowChartInner
        {...props}
        isFullscreen={false}
        onToggleFullscreen={
          allowFullscreen ? () => setIsFullscreen(true) : undefined
        }
      />
    </ReactFlowProvider>
  )
}

function slugLabel(value: string): string {
  return value.trim().toLowerCase().split(/\s+/).join('_')
}

/**
 * Build a single-row ``MetricFlowResponse`` from a parent metric's
 * ``metric_scores`` entry. The sequence array is converted into a
 * linear chain of nodes/edges so the same component can render both
 * per-call and aggregate diagrams without two code paths.
 *
 * ``discoveredLabels`` are the LLM-discovered candidates for this row
 * (also persisted under ``metric_scores[parent_id].discovered_labels``)
 * — sequence entries that resolve against those slugs become
 * ``is_discovered`` nodes so the per-call diagram styles them
 * identically to the aggregate one.
 */
export function flowFromSequence(
  parentMetricId: string,
  parentMetricName: string,
  sequence: string[],
  childIdByKey: Record<string, { id: string; name: string }>,
  selectionMode: 'single_choice' | 'multi_label' | null = null,
  discoveredLabels: Array<{ key: string; name?: string }> = [],
): MetricFlowResponse {
  const nodes: MetricFlowResponse['nodes'] = []
  const seenNodeIds = new Set<string>()
  const orderedIds: string[] = []

  const discoveredByKey: Record<string, { name: string }> = {}
  for (const entry of discoveredLabels) {
    const key = slugLabel(entry.key || '')
    if (!key) continue
    if (childIdByKey[key]) continue
    discoveredByKey[key] = { name: entry.name || key.replace(/_/g, ' ') }
  }

  for (const rawKey of sequence) {
    const key = slugLabel(rawKey)
    const child = childIdByKey[key] || childIdByKey[rawKey]
    if (child) {
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
      continue
    }
    const disc = discoveredByKey[key]
    if (disc) {
      const nodeId = `disc:${key}`
      if (!seenNodeIds.has(nodeId)) {
        seenNodeIds.add(nodeId)
        nodes.push({
          id: nodeId,
          label: disc.name,
          count: 1,
          is_terminal: false,
          is_discovered: true,
        })
      }
      orderedIds.push(nodeId)
    }
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
