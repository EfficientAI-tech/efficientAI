import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
  useEdgesState,
  useNodesState,
} from '@xyflow/react'
import dagre from 'dagre'
import { Maximize2, Minimize2 } from 'lucide-react'
import '@xyflow/react/dist/style.css'
import { metricTreeValues } from './dashboardSelectors'
import { useDashboardNav } from './dashboardNav'
import { useDashboardFilters } from './useDashboardFilters'
import {
  METRIC_LEVEL_COLORS,
  MOCK_AGENTS,
  buildScopedMetricTree,
  scenariosForAgent,
  type MetricLevel,
} from './mockCatalog'
import SectionShell from './SectionShell'

interface TreeNodeData extends Record<string, unknown> {
  label: string
  value: string
  level: MetricLevel
  color: string
  kind: 'metric' | 'scenario'
}

const NODE_WIDTH = 200
const NODE_HEIGHT = 78
const LEVEL_COPY: Record<MetricLevel, string> = {
  0: 'North star',
  1: 'L1 outcomes',
  2: 'L2 drivers',
  3: 'L3 signals',
}
const SCENARIO_COLOR = '#64748b'

function TreeNode({ data }: NodeProps<Node<TreeNodeData>>) {
  const role = data.kind === 'scenario' ? 'Scenario' : LEVEL_COPY[data.level]
  return (
    <div
      className={`rounded-lg border bg-white px-3 py-2.5 ${data.kind === 'scenario' ? 'border-dashed' : ''}`}
      style={{ width: NODE_WIDTH, borderColor: data.color }}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0" style={{ background: data.color }} />
      <p className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: data.color }}>
        {role}
      </p>
      <p className="mt-0.5 truncate text-sm font-semibold text-gray-900">{data.label}</p>
      <p className="mt-1 text-xs tabular-nums text-gray-500">{data.value}</p>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0" style={{ background: data.color }} />
    </div>
  )
}

const nodeTypes = { treeNode: TreeNode }

function layoutTree(nodes: Node<TreeNodeData>[], edges: Edge[]) {
  const graph = new dagre.graphlib.Graph()
  graph.setDefaultEdgeLabel(() => ({}))
  graph.setGraph({ rankdir: 'LR', nodesep: 28, ranksep: 90, edgesep: 18 })
  nodes.forEach((node) => graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT }))
  edges.forEach((edge) => graph.setEdge(edge.source, edge.target))
  dagre.layout(graph)
  return nodes.map((node) => {
    const placed = graph.node(node.id)
    return {
      ...node,
      position: { x: placed.x - NODE_WIDTH / 2, y: placed.y - NODE_HEIGHT / 2 },
    }
  })
}

function MetricTreeFlow({
  expanded,
  agentId,
  scenarioId,
}: {
  expanded: boolean
  agentId: string | null
  scenarioId: string | null
}) {
  const nav = useDashboardNav()
  const scopedCalls = useMemo(
    () =>
      nav.calls.filter((call) => {
        if (agentId && call.agentId !== agentId) return false
        if (scenarioId && call.scenarioId !== scenarioId) return false
        return true
      }),
    [agentId, nav.calls, scenarioId],
  )
  const values = useMemo(() => metricTreeValues(scopedCalls), [scopedCalls])
  const tree = useMemo(() => buildScopedMetricTree(agentId, scenarioId), [agentId, scenarioId])

  const built = useMemo(() => {
    const rawNodes: Node<TreeNodeData>[] = tree.map((item) => ({
      id: item.id,
      type: 'treeNode',
      position: { x: 0, y: 0 },
      data: {
        label: item.name,
        value: item.kind === 'scenario' ? 'supports north star' : (values[item.id]?.display ?? '—'),
        level: item.level,
        color: item.kind === 'scenario' ? SCENARIO_COLOR : METRIC_LEVEL_COLORS[item.level],
        kind: item.kind ?? 'metric',
      },
    }))
    const rawEdges: Edge[] = tree.flatMap((item) =>
      item.drives.map((target) => ({
        id: `${item.id}->${target}`,
        source: item.id,
        target,
        type: 'smoothstep',
        animated: item.level === 1 || item.kind === 'scenario',
        style: {
          stroke: item.kind === 'scenario' ? SCENARIO_COLOR : METRIC_LEVEL_COLORS[item.level],
          strokeWidth: item.level === 1 ? 2 : 1.4,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: item.kind === 'scenario' ? SCENARIO_COLOR : METRIC_LEVEL_COLORS[item.level],
          width: 16,
          height: 16,
        },
      })),
    )
    return { nodes: layoutTree(rawNodes, rawEdges), edges: rawEdges }
  }, [tree, values])

  const [nodes, setNodes, onNodesChange] = useNodesState(built.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(built.edges)

  useEffect(() => {
    setNodes(built.nodes)
    setEdges(built.edges)
  }, [built.edges, built.nodes, setEdges, setNodes])

  return (
    <div className={expanded ? 'h-full w-full' : 'h-[70vh] min-h-[520px] overflow-hidden rounded-lg border border-gray-200 bg-white'}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        minZoom={0.5}
        maxZoom={1.6}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          if (node.id === 'north-star' || node.data.kind === 'scenario') return
          nav.openMetricCalls(node.id, agentId, scenarioId)
        }}
      >
        <Background color="#e5e7eb" gap={18} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

export default function MetricTreePage() {
  const nav = useDashboardNav()
  const filters = useDashboardFilters()
  const [expanded, setExpanded] = useState(false)
  const [agentId, setAgentId] = useState<string | null>(filters.agentId)
  const [scenarioId, setScenarioId] = useState<string | null>(filters.scenarioId)
  const scenarios = agentId ? scenariosForAgent(agentId) : []

  const legend = (
    <div className="flex flex-wrap gap-2">
      {([0, 1, 2, 3] as MetricLevel[]).map((level) => (
        <span
          key={level}
          className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium"
          style={{ borderColor: METRIC_LEVEL_COLORS[level], color: METRIC_LEVEL_COLORS[level] }}
        >
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: METRIC_LEVEL_COLORS[level] }} />
          {LEVEL_COPY[level]}
        </span>
      ))}
      <span
        className="inline-flex items-center gap-1.5 rounded-full border border-dashed px-2 py-0.5 text-[11px] font-medium"
        style={{ borderColor: SCENARIO_COLOR, color: SCENARIO_COLOR }}
      >
        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: SCENARIO_COLOR }} />
        Scenario
      </span>
    </div>
  )

  const filtersBar = (
    <div className="flex flex-wrap items-center gap-2">
      <select
        aria-label="Filter metric tree by agent"
        value={agentId ?? ''}
        onChange={(event) => {
          const next = event.target.value || null
          setAgentId(next)
          setScenarioId(null)
          filters.setParams({ agent: next, scenario: null })
        }}
        className="rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700"
      >
        <option value="">All agents</option>
        {MOCK_AGENTS.map((agent) => (
          <option key={agent.id} value={agent.id}>
            {agent.name}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter metric tree by scenario"
        value={scenarioId ?? ''}
        disabled={!agentId}
        onChange={(event) => {
          const next = event.target.value || null
          setScenarioId(next)
          filters.setParams({ scenario: next })
        }}
        className="rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 disabled:text-gray-400"
      >
        <option value="">{agentId ? 'All scenarios' : 'Select an agent first'}</option>
        {scenarios.map((scenario) => (
          <option key={scenario.id} value={scenario.id}>
            {scenario.name}
          </option>
        ))}
      </select>
    </div>
  )

  const body = (
    <div className={expanded ? 'flex h-full flex-col gap-3 p-4' : 'space-y-3'}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Metric tree</h1>
          <p className="mt-1 max-w-2xl text-sm text-gray-500">
            Only the metrics this agent — and, if chosen, this scenario — actually use. Every node still feeds the north star.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
        >
          {expanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          {expanded ? 'Exit full screen' : 'Expand'}
        </button>
      </div>
      {filtersBar}
      {legend}
      <div className={expanded ? 'min-h-0 flex-1' : ''}>
        <ReactFlowProvider key={`${agentId ?? 'all'}:${scenarioId ?? 'all'}`}>
          <MetricTreeFlow expanded={expanded} agentId={agentId} scenarioId={scenarioId} />
        </ReactFlowProvider>
      </div>
    </div>
  )

  if (expanded) {
    return createPortal(
      <div className="fixed inset-0 z-50 bg-slate-50">{body}</div>,
      document.body,
    )
  }

  return (
    <SectionShell section="tree" current="Metric tree" onBack={nav.openOverview}>
      {body}
    </SectionShell>
  )
}
