import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Sparkles, Loader2, RefreshCw, Wand2 } from 'lucide-react'
import { apiClient } from '../../../lib/api'
import { useToast } from '../../../hooks/useToast'
import AIProviderModelPicker from '../../../components/AIProviderModelPicker'
import AgentFlowChart from '../../promptPartials/components/AgentFlowChart'
import AgentPromptSectionView, {
  type PromptHighlightRange,
} from '../../promptPartials/components/AgentPromptSectionView'
import {
  countMappedNodes,
  flowchartNeedsPromptMapping,
  nodeHasValidMapping,
} from '../../promptPartials/flowchartUtils'
import type { AgentFlowGraph, AgentFlowNode } from '../../../types/api'
import { agentSystemPromptTag, partialMatchesAgentPrompt } from './agentFlowchartUtils'

interface AgentPromptVisualizationProps {
  agentId: string
  agentName: string
  promptContent: string
  /** Tag used to link/find the shadow prompt partial. Defaults to system prompt tag. */
  linkTag?: string
  partialNameLabel?: string
}

export default function AgentPromptVisualization({
  agentId,
  agentName,
  promptContent,
  linkTag: linkTagProp,
  partialNameLabel = 'System Prompt',
}: AgentPromptVisualizationProps) {
  const linkTag = linkTagProp ?? agentSystemPromptTag(agentId)
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [selectedFlowNodeId, setSelectedFlowNodeId] = useState<string | null>(null)
  const [promptHighlight, setPromptHighlight] = useState<PromptHighlightRange | null>(null)
  const [previewMode, setPreviewMode] = useState<'raw' | 'preview'>('preview')
  const [nodeMapError, setNodeMapError] = useState<string | null>(null)
  const [llmProvider, setLlmProvider] = useState('')
  const [llmModel, setLlmModel] = useState('')

  const { data: partials = [], isLoading: isLoadingPartials } = useQuery({
    queryKey: ['agent-prompt-partials', agentId, linkTag],
    queryFn: () => apiClient.listPromptPartials(0, 200),
    select: (items) => items.filter((p: { tags?: string[] | null }) => partialMatchesAgentPrompt(p, agentId, linkTag)),
  })

  const linkedPartialId = partials[0]?.id as string | undefined

  const { data: partialDetail, refetch: refetchPartial } = useQuery({
    queryKey: ['prompt-partial', linkedPartialId],
    queryFn: () => apiClient.getPromptPartial(linkedPartialId!),
    enabled: !!linkedPartialId,
    refetchInterval: (query) => {
      const status = query.state.data?.agent_flowchart_status
      return status === 'generating' || status === 'mapping' ? 3000 : false
    },
  })

  const ensurePartialMutation = useMutation({
    mutationFn: async () => {
      if (linkedPartialId) {
        if ((partialDetail?.content || '') !== promptContent) {
          await apiClient.updatePromptPartial(linkedPartialId, {
            content: promptContent,
            change_summary: 'Synced from agent description',
          })
        }
        return linkedPartialId
      }
      if (!promptContent.trim()) {
        throw new Error('Add a prompt description before generating a visualization')
      }
      const created = await apiClient.createPromptPartial({
        name: `${agentName} — ${partialNameLabel}`,
        description: `Flowchart visualization for agent ${agentName}`,
        content: promptContent,
        tags: [linkTag, 'agents', partialNameLabel.toLowerCase().replace(/\s+/g, '-')],
      })
      return created.id as string
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent-prompt-partials', agentId, linkTag] })
    },
  })

  const generateFlowchartMutation = useMutation({
    mutationFn: async (regenerate: boolean) => {
      const partialId = await ensurePartialMutation.mutateAsync()
      return apiClient.generateAgentFlowchart(partialId, {
        regenerate,
        ...(llmProvider ? { provider: llmProvider } : {}),
        ...(llmModel ? { model: llmModel } : {}),
      })
    },
    onSuccess: () => {
      refetchPartial()
      queryClient.invalidateQueries({ queryKey: ['prompt-partial', linkedPartialId] })
      showToast('Flowchart generation started', 'success')
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || err?.message || 'Failed to generate flowchart', 'error')
    },
  })

  const saveLayoutMutation = useMutation({
    mutationFn: (nodes: Array<{ id: string; position_x: number; position_y: number }>) => {
      if (!linkedPartialId) return Promise.reject(new Error('No linked partial'))
      return apiClient.saveAgentFlowchartLayout(linkedPartialId, nodes)
    },
    onSuccess: () => refetchPartial(),
  })

  const mapPromptMutation = useMutation({
    mutationFn: async () => {
      const partialId = linkedPartialId || (await ensurePartialMutation.mutateAsync())
      return apiClient.mapAgentFlowchartPromptSections(partialId, {
        ...(llmProvider ? { provider: llmProvider } : {}),
        ...(llmModel ? { model: llmModel } : {}),
      })
    },
    onSuccess: () => {
      refetchPartial()
      showToast('Prompt mapping started', 'success')
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || 'Failed to map prompt sections', 'error')
    },
  })

  const flowchart: AgentFlowGraph | null | undefined = partialDetail?.agent_flowchart
  const flowchartStatus = partialDetail?.agent_flowchart_status
  const agentPromptContent = partialDetail?.content || promptContent || ''
  const needsPromptMapping = flowchartNeedsPromptMapping(flowchart, agentPromptContent)
  const mappedNodeCount = countMappedNodes(flowchart, agentPromptContent)
  const totalNodeCount = flowchart?.nodes?.length ?? 0
  const isFlowchartJobRunning = flowchartStatus === 'generating' || flowchartStatus === 'mapping'

  const applyNodeHighlight = (node: AgentFlowNode) => {
    const content = agentPromptContent
    if (!nodeHasValidMapping(node, content)) {
      setPromptHighlight(null)
      return
    }
    if (
      node.start_offset != null &&
      node.end_offset != null &&
      node.end_offset > node.start_offset &&
      node.end_offset <= content.length
    ) {
      setPromptHighlight({
        start: node.start_offset,
        end: node.end_offset,
        excerpt: content.slice(node.start_offset, node.end_offset),
      })
      setPreviewMode('preview')
      return
    }
    if (node.prompt_excerpt) {
      const idx = content.indexOf(node.prompt_excerpt)
      if (idx >= 0) {
        setPromptHighlight({
          start: idx,
          end: idx + node.prompt_excerpt.length,
          excerpt: node.prompt_excerpt,
        })
        setPreviewMode('preview')
        return
      }
      setPromptHighlight({
        start: 0,
        end: 0,
        excerpt: node.prompt_excerpt,
      })
      setPreviewMode('preview')
    }
  }

  const handleFlowNodeClick = (nodeId: string) => {
    setSelectedFlowNodeId(nodeId)
    setNodeMapError(null)
    const node = flowchart?.nodes?.find((item) => item.id === nodeId)
    if (!node) return
    if (nodeHasValidMapping(node, agentPromptContent)) {
      applyNodeHighlight(node)
      return
    }
    setPromptHighlight(null)
    setNodeMapError('Prompt section not mapped for this node. Click "Map prompt sections" to map all nodes.')
  }

  useEffect(() => {
    if (flowchartStatus === 'mapping') return
    const mappingError = flowchart?.mapping_error
    if (mappingError) {
      setNodeMapError(mappingError)
      return
    }
    if (!selectedFlowNodeId || !flowchart?.nodes?.length) return
    const node = flowchart.nodes.find((item) => item.id === selectedFlowNodeId)
    if (node && nodeHasValidMapping(node, agentPromptContent)) {
      applyNodeHighlight(node)
    }
  }, [flowchartStatus, flowchart?.mapping_error, flowchart?.nodes, selectedFlowNodeId, agentPromptContent])

  if (!promptContent.trim()) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-12 text-center text-sm text-gray-500">
        Add a test agent prompt to generate a flowchart visualization.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <AIProviderModelPicker
          provider={llmProvider}
          model={llmModel}
          onProviderChange={(p) => {
            setLlmProvider(p)
            setLlmModel('')
          }}
          onModelChange={(m) => {
            setLlmModel(m)
          }}
          size="sm"
          showAdvancedOptions={false}
        />
        <button
          type="button"
          onClick={() => generateFlowchartMutation.mutate(!!flowchart?.nodes?.length)}
          disabled={generateFlowchartMutation.isPending || isFlowchartJobRunning || isLoadingPartials}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          {generateFlowchartMutation.isPending || flowchartStatus === 'generating' ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Sparkles className="h-3.5 w-3.5" />
          )}
          {flowchart?.nodes?.length ? 'Regenerate' : 'Generate flowchart'}
        </button>
        {flowchart?.nodes?.length ? (
          <>
            <button
              type="button"
              onClick={() => mapPromptMutation.mutate()}
              disabled={mapPromptMutation.isPending || isFlowchartJobRunning}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-primary-300 bg-primary-50 text-primary-700 hover:bg-primary-100 disabled:opacity-50"
            >
              {mapPromptMutation.isPending || flowchartStatus === 'mapping' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Wand2 className="h-3.5 w-3.5" />
              )}
              Map prompt sections
            </button>
            {totalNodeCount > 0 && (
              <span className="text-xs text-gray-500">
                {mappedNodeCount}/{totalNodeCount} nodes mapped
                {needsPromptMapping && ' · mapping needed'}
              </span>
            )}
          </>
        ) : null}
      </div>

      {nodeMapError && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">{nodeMapError}</p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 min-h-[480px]">
        <div className="border border-gray-200 rounded-lg overflow-hidden flex flex-col bg-gray-50 min-h-[400px]">
          <div className="px-4 py-2 border-b border-gray-200 bg-gray-100/80 text-sm font-medium text-gray-900">
            Prompt
          </div>
          <div className="flex-1 overflow-y-auto">
            <AgentPromptSectionView
              content={agentPromptContent}
              highlight={promptHighlight}
              previewMode={previewMode}
            />
          </div>
        </div>

        <div className="border border-gray-200 rounded-lg overflow-hidden flex flex-col bg-white min-h-[400px]">
          <div className="px-4 py-2 border-b border-gray-200 bg-gray-100/80 flex items-center justify-between">
            <span className="text-sm font-medium text-gray-900">Flowchart</span>
            {isFlowchartJobRunning && (
              <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                <RefreshCw className="h-3 w-3 animate-spin" />
                {flowchartStatus}…
              </span>
            )}
          </div>
          <div className="flex-1 min-h-[360px]">
            {flowchart?.nodes?.length ? (
              <AgentFlowChart
                data={flowchart}
                title={agentName}
                onSaveLayout={(nodes) => saveLayoutMutation.mutate(nodes)}
                savingLayout={saveLayoutMutation.isPending}
                highlightNodeId={selectedFlowNodeId}
                onNodeClick={handleFlowNodeClick}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-sm text-gray-400 p-8 text-center">
                {isFlowchartJobRunning
                  ? 'Generating flowchart…'
                  : 'Click "Generate flowchart" to visualize this agent prompt.'}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
