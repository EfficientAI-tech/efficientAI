import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorDetail } from '../../lib/authSession'
import Button from '../../components/Button'
import ToolConnectionLogo from './ToolConnectionLogo'
import type {
  ToolConnection,
  ToolConnectionSecrets,
  ToolSideEffect,
  ToolSimulationMode,
} from '../../types/api'
import {
  HTTP_TOOLS_PLACEHOLDER,
  SIMULATION_MODE_OPTIONS,
  TOOL_CONNECTION_PRESETS,
  presetById,
  type McpTransport,
  type ToolConnectionPreset,
} from './toolConnectionPresets'

interface Props {
  /** Edit this connection; omit to create a new one. */
  connection?: ToolConnection
  onClose: () => void
  onSaved: (connection: ToolConnection) => void
}

interface SecretRow {
  key: string
  value: string
}

const inputClass =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500'

function rowsFor(names: string[] | undefined): SecretRow[] {
  return (names ?? []).map((key) => ({ key, value: '' }))
}

function rowsToRecord(rows: SecretRow[]): Record<string, string> {
  return Object.fromEntries(rows.filter((r) => r.key.trim() && r.value.trim()).map((r) => [r.key.trim(), r.value]))
}

/** Key/value inputs for secret headers or env vars; values are write-only. */
function SecretRows({
  label,
  rows,
  onChange,
  stored,
  onRemoveStored,
}: {
  label: string
  rows: SecretRow[]
  onChange: (rows: SecretRow[]) => void
  stored: string[]
  onRemoveStored: (key: string) => void
}) {
  return (
    <div>
      <div className="mb-1 text-sm font-medium text-gray-700">{label}</div>
      {stored.length ? (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {stored.map((key) => (
            <span
              key={key}
              className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-700"
            >
              {key} · saved
              <button
                type="button"
                onClick={() => onRemoveStored(key)}
                className="text-gray-400 hover:text-red-600"
                aria-label={`Remove ${key}`}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <div className="space-y-2">
        {rows.map((row, index) => (
          <div key={index} className="flex gap-2">
            <input
              value={row.key}
              onChange={(e) => onChange(rows.map((r, i) => (i === index ? { ...r, key: e.target.value } : r)))}
              className={`${inputClass} w-2/5 font-mono`}
              placeholder="NAME"
              aria-label={`${label} name`}
            />
            <input
              type="password"
              value={row.value}
              onChange={(e) => onChange(rows.map((r, i) => (i === index ? { ...r, value: e.target.value } : r)))}
              className={inputClass}
              placeholder={stored.includes(row.key) ? 'Leave blank to keep the saved value' : 'value'}
              autoComplete="off"
              aria-label={`${label} value`}
            />
            <button
              type="button"
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
              className="text-gray-400 hover:text-red-600"
              aria-label="Remove row"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={() => onChange([...rows, { key: '', value: '' }])}
        className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:underline"
      >
        <Plus className="h-3.5 w-3.5" /> Add
      </button>
    </div>
  )
}

export default function ToolConnectionModal({ connection, onClose, onSaved }: Props) {
  const queryClient = useQueryClient()
  const editing = Boolean(connection)
  const config = (connection?.config ?? {}) as Record<string, unknown>
  const [preset, setPreset] = useState<ToolConnectionPreset | undefined>(
    connection ? presetById(connection.preset) : undefined,
  )
  const connectionType = connection?.connection_type ?? preset?.connectionType
  const storedKeys = connection?.secret_keys ?? []

  const [name, setName] = useState(connection?.name ?? '')
  const [mode, setMode] = useState<ToolSimulationMode>(connection?.simulation_mode ?? 'mock_writes')
  const [transport, setTransport] = useState<McpTransport>((config.transport as McpTransport) ?? 'streamable_http')
  const [url, setUrl] = useState((config.url as string) ?? (config.base_url as string) ?? '')
  const [command, setCommand] = useState((config.command as string) ?? '')
  const [args, setArgs] = useState(((config.args as string[]) ?? []).join('\n'))
  const [httpTools, setHttpTools] = useState(
    config.tools ? JSON.stringify(config.tools, null, 2) : HTTP_TOOLS_PLACEHOLDER,
  )
  const [schemas, setSchemas] = useState(((config.schemas as string[]) ?? ['public']).join(', '))
  const [maxRows, setMaxRows] = useState(String(config.max_rows ?? 50))
  const [dsn, setDsn] = useState('')
  const [headerRows, setHeaderRows] = useState<SecretRow[]>([])
  const [envRows, setEnvRows] = useState<SecretRow[]>([])
  const [removedKeys, setRemovedKeys] = useState<string[]>([])
  const [sideEffects, setSideEffects] = useState<Record<string, ToolSideEffect>>(
    (config.tool_side_effects as Record<string, ToolSideEffect>) ?? {},
  )
  const [error, setError] = useState<string | null>(null)

  const choosePreset = (next: ToolConnectionPreset) => {
    setPreset(next)
    setName(next.defaultName)
    setMode(next.simulationMode)
    setTransport(next.transport ?? 'streamable_http')
    setUrl(next.url ?? '')
    setCommand(next.command ?? '')
    setArgs((next.args ?? []).join('\n'))
    setHeaderRows(rowsFor(next.secretHeaders))
    setEnvRows(rowsFor(next.secretEnv))
  }

  const buildPayload = () => {
    let nextConfig: Record<string, unknown>
    if (connectionType === 'http') {
      let tools: unknown
      try {
        tools = JSON.parse(httpTools)
      } catch {
        throw new Error('Tools must be valid JSON')
      }
      nextConfig = { base_url: url.trim(), tools }
    } else if (connectionType === 'postgres') {
      nextConfig = {
        schemas: schemas
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        max_rows: Number(maxRows) || 50,
      }
    } else {
      nextConfig =
        transport === 'stdio'
          ? {
              transport,
              command: command.trim(),
              args: args
                .split('\n')
                .map((a) => a.trim())
                .filter(Boolean),
            }
          : { transport, url: url.trim() }
      if (Object.keys(sideEffects).length) nextConfig.tool_side_effects = sideEffects
    }
    const secrets: ToolConnectionSecrets = {}
    const headers = rowsToRecord(headerRows)
    const env = rowsToRecord(envRows)
    for (const key of removedKeys) {
      const [field, sub] = key.split('.')
      if (field === 'headers' && sub) headers[sub] = ''
      if (field === 'env' && sub) env[sub] = ''
      if (field === 'dsn') secrets.dsn = ''
    }
    if (Object.keys(headers).length) secrets.headers = headers
    if (Object.keys(env).length) secrets.env = env
    if (dsn.trim()) secrets.dsn = dsn.trim()
    return { config: nextConfig, secrets }
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      const { config: nextConfig, secrets } = buildPayload()
      if (connection) {
        return apiClient.updateToolConnection(connection.id, {
          name: name.trim(),
          config: nextConfig,
          secrets: Object.keys(secrets).length ? secrets : undefined,
          simulation_mode: mode,
        })
      }
      return apiClient.createToolConnection({
        name: name.trim(),
        connection_type: connectionType!,
        preset: preset?.id,
        config: nextConfig,
        secrets,
        simulation_mode: mode,
      })
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['tool-connections'] })
      onSaved(saved)
    },
    onError: (err: unknown) =>
      setError(getApiErrorDetail(err) ?? (err instanceof Error ? err.message : 'Save failed')),
  })

  const storedFor = (field: string) =>
    storedKeys
      .filter((key) => key.startsWith(`${field}.`) && !removedKeys.includes(key))
      .map((key) => key.slice(field.length + 1))
  const removeStored = (field: string) => (key: string) => setRemovedKeys((prev) => [...prev, `${field}.${key}`])

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-gray-500 bg-opacity-75 p-4">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
              {connectionType ? (
                <ToolConnectionLogo preset={preset?.id ?? connection?.preset} connectionType={connectionType} size={22} />
              ) : null}
              {editing ? `Edit ${connection!.name}` : preset ? `Connect ${preset.label}` : 'Connect a tool source'}
            </h2>
            <p className="text-sm text-gray-500">
              Production agents you attach it to can call its tools during simulations.
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-4">
          {!connectionType ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {TOOL_CONNECTION_PRESETS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => choosePreset(option)}
                  className="flex items-start gap-3 rounded-lg border border-gray-200 p-3 text-left hover:border-primary-400 hover:bg-primary-50"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-gray-100 bg-white">
                    <ToolConnectionLogo preset={option.id} connectionType={option.connectionType} size={20} />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-gray-900">{option.label}</span>
                    <span className="mt-0.5 block text-xs text-gray-500">{option.description}</span>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Name</label>
                <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
                <p className="mt-1 text-xs text-gray-500">
                  Tools are exposed to the agent as{' '}
                  <span className="font-mono">{connection?.slug ?? 'name'}__tool_name</span>.
                </p>
              </div>

              {connectionType === 'mcp' ? (
                <>
                  <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">Transport</label>
                    <select
                      value={transport}
                      onChange={(e) => setTransport(e.target.value as McpTransport)}
                      className={inputClass}
                    >
                      <option value="streamable_http">HTTP (streamable)</option>
                      <option value="sse">HTTP + SSE (legacy)</option>
                      <option value="stdio">Local command (stdio, self-hosted only)</option>
                    </select>
                  </div>
                  {transport === 'stdio' ? (
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_2fr]">
                      <div>
                        <label className="mb-1 block text-sm font-medium text-gray-700">Command</label>
                        <input value={command} onChange={(e) => setCommand(e.target.value)} className={`${inputClass} font-mono`} />
                      </div>
                      <div>
                        <label className="mb-1 block text-sm font-medium text-gray-700">Arguments (one per line)</label>
                        <textarea
                          value={args}
                          onChange={(e) => setArgs(e.target.value)}
                          rows={2}
                          className={`${inputClass} font-mono`}
                        />
                      </div>
                    </div>
                  ) : (
                    <div>
                      <label className="mb-1 block text-sm font-medium text-gray-700">Server URL</label>
                      <input
                        value={url}
                        onChange={(e) => setUrl(e.target.value)}
                        className={`${inputClass} font-mono`}
                        placeholder="https://mcp.example.com/mcp"
                      />
                    </div>
                  )}
                  {transport === 'stdio' ? (
                    <SecretRows
                      label="Secret environment variables"
                      rows={envRows}
                      onChange={setEnvRows}
                      stored={storedFor('env')}
                      onRemoveStored={removeStored('env')}
                    />
                  ) : (
                    <SecretRows
                      label="Secret headers"
                      rows={headerRows}
                      onChange={setHeaderRows}
                      stored={storedFor('headers')}
                      onRemoveStored={removeStored('headers')}
                    />
                  )}
                </>
              ) : null}

              {connectionType === 'http' ? (
                <>
                  <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">Base URL</label>
                    <input
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      className={`${inputClass} font-mono`}
                      placeholder="https://api.example.com"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">Tools (JSON)</label>
                    <textarea
                      value={httpTools}
                      onChange={(e) => setHttpTools(e.target.value)}
                      rows={12}
                      className={`${inputClass} font-mono text-xs`}
                    />
                  </div>
                  <SecretRows
                    label="Secret headers"
                    rows={headerRows}
                    onChange={setHeaderRows}
                    stored={storedFor('headers')}
                    onRemoveStored={removeStored('headers')}
                  />
                </>
              ) : null}

              {connectionType === 'postgres' ? (
                <>
                  <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">Connection string</label>
                    <input
                      type="password"
                      value={dsn}
                      onChange={(e) => setDsn(e.target.value)}
                      className={`${inputClass} font-mono`}
                      placeholder={
                        storedKeys.includes('dsn') ? 'Saved — leave blank to keep it' : 'postgresql://reader:password@host:5432/db'
                      }
                      autoComplete="off"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1 block text-sm font-medium text-gray-700">Schemas</label>
                      <input value={schemas} onChange={(e) => setSchemas(e.target.value)} className={inputClass} />
                    </div>
                    <div>
                      <label className="mb-1 block text-sm font-medium text-gray-700">Max rows per query</label>
                      <input
                        type="number"
                        min={1}
                        max={500}
                        value={maxRows}
                        onChange={(e) => setMaxRows(e.target.value)}
                        className={inputClass}
                      />
                    </div>
                  </div>
                </>
              ) : null}

              <fieldset>
                <legend className="mb-1 text-sm font-medium text-gray-700">In simulations</legend>
                <div className="space-y-1.5">
                  {SIMULATION_MODE_OPTIONS.map((option) => (
                    <label key={option.value} className="flex cursor-pointer items-start gap-2 text-sm">
                      <input
                        type="radio"
                        name="simulation-mode"
                        checked={mode === option.value}
                        onChange={() => setMode(option.value)}
                        className="mt-1"
                      />
                      <span>
                        <span className="font-medium text-gray-900">{option.label}</span>
                        <span className="text-gray-500"> — {option.description}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              {editing && connectionType === 'mcp' && connection!.tools.length ? (
                <div>
                  <div className="mb-1 text-sm font-medium text-gray-700">Read or write</div>
                  <p className="mb-2 text-xs text-gray-500">
                    Writes are mocked in “Mock writes” mode. Override the guess for any tool.
                  </p>
                  <ul className="max-h-48 divide-y divide-gray-100 overflow-y-auto rounded-lg border border-gray-200">
                    {connection!.tools.map((tool) => (
                      <li key={tool.name} className="flex items-center justify-between gap-3 px-3 py-1.5 text-sm">
                        <span className="truncate font-mono text-gray-900">{tool.name}</span>
                        <select
                          value={sideEffects[tool.name] ?? tool.side_effect}
                          onChange={(e) =>
                            setSideEffects((prev) => ({ ...prev, [tool.name]: e.target.value as ToolSideEffect }))
                          }
                          className="rounded border border-gray-300 px-2 py-1 text-xs"
                          aria-label={`${tool.name} side effect`}
                        >
                          <option value="read">Read</option>
                          <option value="write">Write</option>
                        </select>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {preset?.hint ? <p className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{preset.hint}</p> : null}
              {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}
            </>
          )}
        </div>

        <div className="flex justify-end gap-3 border-t border-gray-200 px-6 py-4">
          {!editing && connectionType ? (
            <Button variant="outline" onClick={() => setPreset(undefined)} className="mr-auto">
              Back
            </Button>
          ) : null}
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          {connectionType ? (
            <Button
              variant="primary"
              isLoading={saveMutation.isPending}
              disabled={!name.trim()}
              onClick={() => {
                setError(null)
                saveMutation.mutate()
              }}
            >
              {editing ? 'Save and re-test' : 'Connect and discover tools'}
            </Button>
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}
