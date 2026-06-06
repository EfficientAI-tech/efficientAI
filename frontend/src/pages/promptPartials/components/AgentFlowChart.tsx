import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import { Loader2, Maximize2, Minimize2, RotateCcw, Save } from 'lucide-react'
import '@xyflow/react/dist/style.css'

import type { AgentFlowGraph } from '../../../types/api'

interface AgentFlowNodeData extends Record<string, unknown> {
  label: string
  nodeType: 'start' | 'decision' | 'action' | 'terminal'
}

const NODE_WIDTH = 190
const NODE_HEIGHT = 72

function AgentFlowNode({ data }: NodeProps<Node<AgentFlowNodeData>>) {
  let accent = 'border-gray-300'
  if (data.nodeType === 'start') accent = 'border-gray-400 border-dashed'
  else if (data.nodeType === 'decision') accent = 'border-amber-500 bg-amber-50/40'
  else if (data.nodeType === 'terminal') accent = 'border-blue-500'
  else accent = 'border-slate-300'

  const shape =
    data.nodeType === 'decision'
      ? 'rounded-lg'
      : data.nodeType === 'terminal'
        ? 'rounded-full'
        : 'rounded-md'

  return (
    <div
      className={`bg-white px-3 py-2 shadow-sm border-2 ${accent} ${shape}`}
      style={{ width: NODE_WIDTH, minHeight: NODE_HEIGHT }}
    >
      <Handle type="target" position={Position.Left} className="opacity-0" />
      <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">
        {data.nodeType}
      </div>
      <div className="text-xs font-semibold text-gray-800">{data.label}</div>
      <Handle type="source" position={Position.Right} className="opacity-0" />
    </div>
  )
}

const nodeTypes = { agentFlowNode: AgentFlowNode }

function layoutWithDagre(
  nodes: Node<AgentFlowNodeData>[],
  edges: Edge[],
): { nodes: Node<AgentFlowNodeData>[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 120, edgesep: 24 })

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

function buildFlowNodes(data: AgentFlowGraph): Node<AgentFlowNodeData>[] {
  const hasSavedPositions = data.nodes.some(
    (n) => n.position_x != null && n.position_y != null,
  )
  const baseNodes: Node<AgentFlowNodeData>[] = data.nodes.map((n) => ({
    id: n.id,
    type: 'agentFlowNode',
    position: {
      x: n.position_x ?? 0,
      y: n.position_y ?? 0,
    },
    data: {
      label: n.label,
      nodeType: n.node_type,
    },
  }))
  if (hasSavedPositions) return baseNodes
  return baseNodes
}

function buildFlowEdges(data: AgentFlowGraph): Edge[] {
  return data.edges.map((e) => ({
    id: `${e.source}->${e.target}:${e.condition || ''}`,
    source: e.source,
    target: e.target,
    type: 'smoothstep',
    animated: false,
    style: { stroke: '#64748b', strokeWidth: 2 },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: '#64748b',
    },
    label: e.condition || undefined,
    labelBgPadding: [4, 2] as [number, number],
    labelBgBorderRadius: 4,
    labelBgStyle: { fill: '#fff7ed', fillOpacity: 0.95 },
    labelStyle: { fontSize: 10, fill: '#9a3412', fontWeight: 600 },
  }))
}

function AgentFlowChartInner({
  data,
  height = 420,
  title,
  isFullscreen,
  onToggleFullscreen,
  onSaveLayout,
  savingLayout,
  layoutDirty,
  onLayoutDirtyChange,
}: {
  data: AgentFlowGraph
  height?: number
  title?: string
  isFullscreen?: boolean
  onToggleFullscreen?: () => void
  onSaveLayout?: (nodes: Node<AgentFlowNodeData>[]) => void
  savingLayout?: boolean
  layoutDirty?: boolean
  onLayoutDirtyChange?: (dirty: boolean) => void
}) {
  const { fitView } = useReactFlow()

  const initialLayout = useMemo(() => {
    const initialNodes = buildFlowNodes(data)
    const initialEdges = buildFlowEdges(data)
    const hasSavedPositions = data.nodes.some(
      (n) => n.position_x != null && n.position_y != null,
    )
    if (hasSavedPositions) {
      return { nodes: initialNodes, edges: initialEdges }
    }
    return layoutWithDagre(initialNodes, initialEdges)
  }, [data])

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<AgentFlowNodeData>>(
    initialLayout.nodes,
  )
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initialLayout.edges)
  const skipDirtyRef = useRef(true)

  useEffect(() => {
    skipDirtyRef.current = true
    setNodes(initialLayout.nodes)
    setEdges(initialLayout.edges)
    onLayoutDirtyChange?.(false)
  }, [initialLayout, setNodes, setEdges, onLayoutDirtyChange])

  useEffect(() => {
    const handle = setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 50)
    return () => clearTimeout(handle)
  }, [initialLayout, isFullscreen, fitView])

  const resetLayout = useCallback(() => {
    const laidOut = layoutWithDagre(
      buildFlowNodes({ ...data, nodes: data.nodes.map((n) => ({ ...n, position_x: null, position_y: null })) }),
      buildFlowEdges(data),
    )
    skipDirtyRef.current = true
    setNodes(laidOut.nodes)
    setEdges(laidOut.edges)
    onLayoutDirtyChange?.(false)
    setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 50)
  }, [data, setNodes, setEdges, fitView, onLayoutDirtyChange])

  const handleNodesChange = useCallback(
    (changes: Parameters<typeof onNodesChange>[0]) => {
      onNodesChange(changes)
      const moved = changes.some((c) => c.type === 'position' && c.dragging === false)
      if (moved) {
        if (skipDirtyRef.current) {
          skipDirtyRef.current = false
        } else {
          onLayoutDirtyChange?.(true)
        }
      }
    },
    [onNodesChange, onLayoutDirtyChange],
  )

  const chartToolBtn =
    'inline-flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded-md border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-40'

  return (
    <div
      className={
        isFullscreen
          ? 'flex flex-col h-full bg-gray-50'
          : 'h-full overflow-hidden relative flex flex-col border-0'
      }
      style={isFullscreen ? undefined : { height: height ?? '100%' }}
    >
      <div
        className={`flex items-center justify-between px-3 py-2 border-b border-gray-200 bg-white ${
          isFullscreen ? '' : 'relative z-10'
        }`}
      >
        <p className="text-xs text-gray-500">
          {data.nodes.length} nodes · {data.edges.length} transitions
          {layoutDirty ? ' · unsaved changes' : ''}
        </p>
        <div className="flex items-center gap-1.5">
          {onSaveLayout ? (
            <button
              type="button"
              onClick={() => onSaveLayout(nodes)}
              disabled={!layoutDirty || savingLayout}
              className={chartToolBtn}
            >
              {savingLayout ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Save className="h-3 w-3" />
              )}
              Save layout
            </button>
          ) : null}
          <button type="button" onClick={resetLayout} className={chartToolBtn}>
            <RotateCcw className="h-3 w-3" />
            Reset
          </button>
          {onToggleFullscreen ? (
            <button type="button" onClick={onToggleFullscreen} className={chartToolBtn}>
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
          ) : null}
        </div>
      </div>
      <div className="flex-1 min-h-0">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={handleNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          nodesDraggable
          nodesConnectable={false}
          elementsSelectable
          fitView
          minZoom={0.2}
          maxZoom={1.5}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} size={1} color="#e2e8f0" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {isFullscreen && title ? (
        <p className="sr-only">{title}</p>
      ) : null}
    </div>
  )
}

export default function AgentFlowChart({
  data,
  height,
  title,
  onSaveLayout,
  savingLayout,
}: {
  data: AgentFlowGraph
  height?: number
  title?: string
  onSaveLayout?: (nodes: Array<{ id: string; position_x: number; position_y: number }>) => void
  savingLayout?: boolean
}) {
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [layoutDirty, setLayoutDirty] = useState(false)

  useEffect(() => {
    if (!isFullscreen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsFullscreen(false)
    }
    window.addEventListener('keydown', handler)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', handler)
      document.body.style.overflow = prevOverflow
    }
  }, [isFullscreen])

  const handleSave = useCallback(
    (nodes: Node<AgentFlowNodeData>[]) => {
      if (!onSaveLayout) return
      onSaveLayout(
        nodes.map((n) => ({
          id: n.id,
          position_x: n.position.x,
          position_y: n.position.y,
        })),
      )
      setLayoutDirty(false)
    },
    [onSaveLayout],
  )

  const inner = (
    <AgentFlowChartInner
      data={data}
      height={height}
      title={title}
      isFullscreen={isFullscreen}
      onToggleFullscreen={() => setIsFullscreen((v) => !v)}
      onSaveLayout={onSaveLayout ? handleSave : undefined}
      savingLayout={savingLayout}
      layoutDirty={layoutDirty}
      onLayoutDirtyChange={setLayoutDirty}
    />
  )

  if (isFullscreen) {
    return createPortal(
      <div className="fixed inset-0 z-50 bg-white flex flex-col">
        <div className="border-b border-gray-200 px-4 py-2 flex items-center justify-between bg-gray-50">
          <p className="text-sm font-semibold text-gray-900">
            {title || 'Agent logic flowchart'}
          </p>
          <p className="text-[11px] text-gray-500">
            Drag nodes to rearrange · Save layout · Esc to close
          </p>
        </div>
        <div className="flex-1 min-h-0">
          <ReactFlowProvider>{inner}</ReactFlowProvider>
        </div>
      </div>,
      document.body,
    )
  }

  return <ReactFlowProvider>{inner}</ReactFlowProvider>
}
