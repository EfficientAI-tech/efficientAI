import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Loader, Plug, RefreshCw, Trash2, Wrench } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import type { ToolConnection } from '../../types/api'
import ToolConnectionLogo from './ToolConnectionLogo'
import ToolConnectionModal from './ToolConnectionModal'
import { SIMULATION_MODE_OPTIONS, presetById } from './toolConnectionPresets'

const TYPE_LABELS: Record<string, string> = { mcp: 'MCP server', http: 'HTTP API', postgres: 'Postgres' }

function sourceLabel(connection: ToolConnection): string {
  return presetById(connection.preset)?.label ?? TYPE_LABELS[connection.connection_type] ?? connection.connection_type
}

/** Health always ships icon + label, never color alone. */
function ConnectionHealth({ connection }: { connection: ToolConnection }) {
  if (connection.last_error) {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-red-700" title={connection.last_error}>
        <AlertTriangle className="h-3.5 w-3.5" /> Failed
      </span>
    )
  }
  if (!connection.last_tested_at) return <span className="text-xs text-gray-500">Not tested</span>
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-green-700">
      <CheckCircle2 className="h-3.5 w-3.5" /> Connected
    </span>
  )
}

/** ``embedded``: rendered as a tab of the Tools page, which supplies the page title. */
export default function ToolConnections({ embedded = false }: { embedded?: boolean }) {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [editing, setEditing] = useState<ToolConnection | null>(null)
  const [creating, setCreating] = useState(false)

  const { data: connections = [], isLoading } = useQuery({
    queryKey: ['tool-connections'],
    queryFn: () => apiClient.listToolConnections(),
  })

  const testMutation = useMutation({
    mutationFn: (id: string) => apiClient.testToolConnection(id),
    onSuccess: (connection) => {
      queryClient.invalidateQueries({ queryKey: ['tool-connections'] })
      if (connection.last_error) showToast(`${connection.name}: ${connection.last_error}`, 'error')
      else showToast(`${connection.name}: ${connection.tools.length} tools found`, 'success')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteToolConnection(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tool-connections'] })
      showToast('Tool connection deleted', 'success')
    },
    onError: (err: Error) => showToast(err.message || 'Delete failed', 'error'),
  })

  const onSaved = (connection: ToolConnection) => {
    setCreating(false)
    setEditing(null)
    if (connection.last_error) showToast(`Saved, but the connection failed: ${connection.last_error}`, 'error')
    else showToast(`${connection.name} connected · ${connection.tools.length} tools`, 'success')
  }

  return (
    <div className="flex h-full flex-col bg-white">
      <ToastContainer />
      <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
        <div>
          {!embedded ? (
            <div className="flex items-center gap-2">
              <Wrench className="h-5 w-5 text-primary-600" />
              <h1 className="text-xl font-semibold text-gray-900">Tools</h1>
            </div>
          ) : null}
          <p className={`text-sm text-gray-500 ${embedded ? '' : 'mt-1'}`}>
            Connect Slack, Notion, Google Drive, Postgres, MCP servers or your own APIs — then attach them to
            agents under Production Agent → Tools → Connections.
          </p>
        </div>
        <Button variant="primary" leftIcon={<Plug className="h-4 w-4" />} onClick={() => setCreating(true)}>
          Connect tools
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Loader className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : connections.length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center">
            <Wrench className="mx-auto h-8 w-8 text-gray-300" />
            <p className="mt-2 text-sm text-gray-600">No tool sources yet.</p>
            <p className="text-xs text-gray-500">
              Simulations then check whether the production agent calls the right tools and whether those calls succeed.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-2">Name</th>
                  <th className="px-4 py-2">Source</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2 text-right">Tools</th>
                  <th className="px-4 py-2">In simulations</th>
                  <th className="px-4 py-2 text-right">Agents</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {connections.map((connection) => (
                  <tr key={connection.id} className="cursor-pointer hover:bg-gray-50" onClick={() => setEditing(connection)}>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-3">
                        <ToolConnectionLogo preset={connection.preset} connectionType={connection.connection_type} />
                        <div>
                          <div className="font-medium text-gray-900">{connection.name}</div>
                          <div className="font-mono text-xs text-gray-500">{connection.slug}__*</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-2 text-gray-700">{sourceLabel(connection)}</td>
                    <td className="px-4 py-2">
                      <ConnectionHealth connection={connection} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {connection.tools.length}
                      {connection.tools.some((t) => t.side_effect === 'write') ? (
                        <span className="ml-1 text-xs text-gray-500">
                          ({connection.tools.filter((t) => t.side_effect === 'write').length} write)
                        </span>
                      ) : null}
                    </td>
                    <td className="px-4 py-2 text-gray-700">
                      {SIMULATION_MODE_OPTIONS.find((o) => o.value === connection.simulation_mode)?.label}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{connection.agent_count}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-right" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        onClick={() => testMutation.mutate(connection.id)}
                        disabled={testMutation.isPending}
                        className="mr-3 text-gray-400 hover:text-primary-600"
                        aria-label={`Re-test ${connection.name}`}
                        title="Re-test and refresh tools"
                      >
                        <RefreshCw
                          className={`h-4 w-4 ${testMutation.isPending && testMutation.variables === connection.id ? 'animate-spin' : ''}`}
                        />
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (window.confirm(`Delete ${connection.name}? Agents using it lose these tools.`)) {
                            deleteMutation.mutate(connection.id)
                          }
                        }}
                        className="text-gray-400 hover:text-red-600"
                        aria-label={`Delete ${connection.name}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {creating ? <ToolConnectionModal onClose={() => setCreating(false)} onSaved={onSaved} /> : null}
      {editing ? (
        <ToolConnectionModal connection={editing} onClose={() => setEditing(null)} onSaved={onSaved} />
      ) : null}
    </div>
  )
}
