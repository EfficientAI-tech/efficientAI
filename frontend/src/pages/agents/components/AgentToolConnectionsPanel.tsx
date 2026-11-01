import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, Zap } from 'lucide-react'
import { apiClient } from '../../../lib/api'
import { getApiErrorDetail } from '../../../lib/authSession'
import Button from '../../../components/Button'
import type { AgentToolConnectionLink } from '../../../types/api'
import ToolConnectionLogo from '../../toolConnections/ToolConnectionLogo'

interface Props {
  agentId: string
}

/** Which tool connections the production agent can call; saved independently of the agent form. */
export default function AgentToolConnectionsPanel({ agentId }: Props) {
  const queryClient = useQueryClient()
  const { data: connections = [] } = useQuery({
    queryKey: ['tool-connections'],
    queryFn: () => apiClient.listToolConnections(),
  })
  const { data: savedLinks } = useQuery({
    queryKey: ['agent-tool-connections', agentId],
    queryFn: () => apiClient.getAgentToolConnections(agentId),
  })
  const { data: catalog = [] } = useQuery({
    queryKey: ['agent-tool-catalog', agentId],
    queryFn: () => apiClient.getAgentToolCatalog(agentId),
  })
  const [links, setLinks] = useState<AgentToolConnectionLink[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (savedLinks) setLinks(savedLinks)
  }, [savedLinks])

  const dirty = useMemo(() => JSON.stringify(links) !== JSON.stringify(savedLinks ?? []), [links, savedLinks])

  const saveMutation = useMutation({
    mutationFn: () => apiClient.updateAgentToolConnections(agentId, links),
    onSuccess: () => {
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['agent-tool-connections', agentId] })
      queryClient.invalidateQueries({ queryKey: ['agent-tool-catalog', agentId] })
      queryClient.invalidateQueries({ queryKey: ['tool-connections'] })
    },
    onError: (err: unknown) => setError(getApiErrorDetail(err) ?? 'Save failed'),
  })

  const linkFor = (connectionId: string) => links.find((l) => l.tool_connection_id === connectionId)

  const toggleConnection = (connectionId: string) =>
    setLinks((prev) =>
      linkFor(connectionId)
        ? prev.filter((l) => l.tool_connection_id !== connectionId)
        : [...prev, { tool_connection_id: connectionId, enabled_tools: null }],
    )

  const toggleTool = (connectionId: string, allTools: string[], tool: string) =>
    setLinks((prev) =>
      prev.map((link) => {
        if (link.tool_connection_id !== connectionId) return link
        const enabled = link.enabled_tools ?? allTools
        const next = enabled.includes(tool) ? enabled.filter((t) => t !== tool) : [...enabled, tool]
        return { ...link, enabled_tools: next.length === allTools.length ? null : next }
      }),
    )

  const kbTools = catalog.filter((entry) => entry.name === 'search_knowledge_base')

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Production agent tools</h3>
          <p className="mt-0.5 text-sm text-gray-500">
            Tools the agent under test can call during simulations. Calls are recorded per turn and scored.
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          disabled={!dirty}
          isLoading={saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          Save tools
        </Button>
      </div>

      {kbTools.length ? (
        <p className="text-xs text-gray-500">
          Also available: <span className="font-mono">search_knowledge_base</span> over the production agent’s
          knowledge bases.
        </p>
      ) : null}

      {connections.length === 0 ? (
        <p className="text-sm text-gray-500">
          No tool sources in this workspace yet.{' '}
          <Link to="/tools" className="text-primary-700 hover:underline">
            Connect Slack, Notion, Postgres or an API
          </Link>
          .
        </p>
      ) : (
        <ul className="space-y-3">
          {connections.map((connection) => {
            const link = linkFor(connection.id)
            const allTools = connection.tools.map((t) => t.name)
            const enabled = link?.enabled_tools ?? allTools
            return (
              <li key={connection.id} className="rounded-lg border border-gray-200 bg-white">
                <label className="flex cursor-pointer items-center gap-3 px-4 py-3">
                  <input type="checkbox" checked={Boolean(link)} onChange={() => toggleConnection(connection.id)} />
                  <ToolConnectionLogo preset={connection.preset} connectionType={connection.connection_type} size={18} />
                  <span className="font-medium text-gray-900">{connection.name}</span>
                  <span className="text-xs text-gray-500">
                    {connection.tools.length} tools
                    {connection.last_error ? <span className="text-red-700"> · connection failing</span> : null}
                  </span>
                </label>
                {link && connection.tools.length ? (
                  <ul className="grid grid-cols-1 gap-x-4 gap-y-1 border-t border-gray-100 px-4 py-2 sm:grid-cols-2">
                    {connection.tools.map((tool) => {
                      const mocked =
                        connection.simulation_mode === 'mock_all' ||
                        (connection.simulation_mode === 'mock_writes' && tool.side_effect === 'write')
                      return (
                        <li key={tool.name}>
                          <label className="flex cursor-pointer items-center gap-2 text-sm" title={tool.description ?? undefined}>
                            <input
                              type="checkbox"
                              checked={enabled.includes(tool.name)}
                              onChange={() => toggleTool(connection.id, allTools, tool.name)}
                            />
                            <span className="truncate font-mono text-xs text-gray-900">{tool.name}</span>
                            {mocked ? (
                              <span className="inline-flex items-center gap-0.5 text-[11px] text-amber-700">
                                <FlaskConical className="h-3 w-3" /> mocked
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-0.5 text-[11px] text-green-700">
                                <Zap className="h-3 w-3" /> live
                              </span>
                            )}
                          </label>
                        </li>
                      )
                    })}
                  </ul>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
      {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}
    </div>
  )
}
