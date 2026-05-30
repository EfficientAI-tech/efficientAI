import { useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  Edit3,
  GripVertical,
  Lock,
  Plus,
  Trash2,
  X,
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import type {
  CallImportSchema,
  CallImportSchemaParameter,
  CallImportSchemaParameterType,
} from '../../types/api'
import Button from '../../components/Button'

const PARAMETER_TYPES: { value: CallImportSchemaParameterType; label: string }[] = [
  { value: 'recording_url', label: 'Recording URL' },
  { value: 'recording_date', label: 'Recording Date' },
  { value: 'transcript', label: 'Transcript' },
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'boolean', label: 'Boolean' },
  { value: 'datetime', label: 'Date-time' },
  { value: 'url', label: 'URL' },
]

interface EditableParameter {
  /** Local-only key — lets React reconcile rows being reordered. */
  key: string
  name: string
  type: CallImportSchemaParameterType
  description: string
  is_required: boolean
}

function makeEmptyParameter(): EditableParameter {
  return {
    key: Math.random().toString(36).slice(2),
    name: '',
    type: 'text',
    description: '',
    is_required: false,
  }
}

function makeConversationIdParameter(): EditableParameter {
  return {
    key: 'conversation_id',
    name: 'conversation_id',
    type: 'conversation_id',
    description: 'Mandatory identifier for each row in the imported batch.',
    is_required: true,
  }
}

function makeRecordingDateParameter(): EditableParameter {
  return {
    key: 'recording_date',
    name: 'recording_date',
    type: 'recording_date',
    description: 'Date the call recording was captured, stored without time.',
    is_required: true,
  }
}

function parametersFromSchema(
  parameters: CallImportSchemaParameter[],
): EditableParameter[] {
  return parameters.map((p, idx) => ({
    key: `${p.name || idx}-${idx}`,
    name: p.name,
    type: p.type,
    description: p.description || '',
    is_required: p.is_required,
  }))
}

function validateParameters(params: EditableParameter[]): string | null {
  if (params.length === 0) return 'Add at least one parameter.'
  const seen = new Set<string>()
  let convCount = 0
  let recordingDateCount = 0
  let recordingCount = 0
  let transcriptCount = 0
  for (const p of params) {
    const name = p.name.trim()
    if (!name) return 'Every parameter needs a name.'
    const lower = name.toLowerCase()
    if (seen.has(lower)) return `Duplicate parameter name "${name}".`
    seen.add(lower)
    if (p.type === 'conversation_id') convCount += 1
    if (p.type === 'recording_date') recordingDateCount += 1
    if (p.type === 'recording_url') recordingCount += 1
    if (p.type === 'transcript') transcriptCount += 1
  }
  if (convCount !== 1) {
    return 'Exactly one parameter must be of type "conversation_id".'
  }
  if (recordingDateCount !== 1) {
    return 'Exactly one parameter must be of type "recording_date".'
  }
  if (recordingCount > 1) {
    return 'At most one parameter can be of type "recording_url".'
  }
  if (transcriptCount > 1) {
    return 'At most one parameter can be of type "transcript".'
  }
  return null
}

interface SchemaEditorProps {
  open: boolean
  schema: CallImportSchema | null
  onClose: () => void
  onSaved: () => void
}

function SchemaEditor({ open, schema, onClose, onSaved }: SchemaEditorProps) {
  const isEditing = schema !== null
  const [name, setName] = useState<string>(schema?.name ?? '')
  const [description, setDescription] = useState<string>(schema?.description ?? '')
  const [parameters, setParameters] = useState<EditableParameter[]>(
    schema
      ? parametersFromSchema(schema.parameters)
      : [makeConversationIdParameter(), makeRecordingDateParameter()],
  )
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const conversationIdIdx = useMemo(
    () => parameters.findIndex((p) => p.type === 'conversation_id'),
    [parameters],
  )

  // Reset local state whenever the editor opens against a new target so a
  // stale parameter list doesn't bleed across edit / new sessions.
  useMemo(() => {
    if (open) {
      setName(schema?.name ?? '')
      setDescription(schema?.description ?? '')
      setParameters(
        schema
          ? parametersFromSchema(schema.parameters)
          : [makeConversationIdParameter(), makeRecordingDateParameter()],
      )
      setErrorMsg(null)
    }
  }, [open, schema])

  const createMutation = useMutation({
    mutationFn: () =>
      apiClient.createCallImportSchema({
        name: name.trim(),
        description: description.trim() || null,
        parameters: parameters.map((p) => ({
          name: p.name.trim(),
          type: p.type,
          description: p.description.trim() || null,
          is_required:
            p.type === 'conversation_id' || p.type === 'recording_date'
              ? true
              : p.is_required,
        })),
      }),
    onSuccess: () => {
      onSaved()
    },
    onError: (err: any) => {
      setErrorMsg(
        err?.response?.data?.detail || err?.message || 'Failed to create schema.',
      )
    },
  })

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!schema) throw new Error('No schema in scope')
      return apiClient.updateCallImportSchema(schema.id, {
        name: name.trim(),
        description: description.trim() || null,
        parameters: parameters.map((p) => ({
          name: p.name.trim(),
          type: p.type,
          description: p.description.trim() || null,
          is_required:
            p.type === 'conversation_id' || p.type === 'recording_date'
              ? true
              : p.is_required,
        })),
      })
    },
    onSuccess: () => {
      onSaved()
    },
    onError: (err: any) => {
      setErrorMsg(
        err?.response?.data?.detail || err?.message || 'Failed to update schema.',
      )
    },
  })

  if (!open) return null

  const handleSave = () => {
    setErrorMsg(null)
    if (!name.trim()) {
      setErrorMsg('Name is required.')
      return
    }
    const err = validateParameters(parameters)
    if (err) {
      setErrorMsg(err)
      return
    }
    if (isEditing) {
      updateMutation.mutate()
    } else {
      createMutation.mutate()
    }
  }

  const isSubmitting = createMutation.isPending || updateMutation.isPending

  const updateParameter = (idx: number, patch: Partial<EditableParameter>) => {
    setParameters((prev) =>
      prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)),
    )
  }

  const removeParameter = (idx: number) => {
    setParameters((prev) => prev.filter((_, i) => i !== idx))
  }

  const moveParameter = (idx: number, direction: 'up' | 'down') => {
    setParameters((prev) => {
      const next = [...prev]
      const target = direction === 'up' ? idx - 1 : idx + 1
      if (target < 0 || target >= next.length) return prev
      // Keep the conversation_id row pinned at the top — it must always
      // be index 0 so the UI can lock it visually.
      if (
        next[idx].type === 'conversation_id' ||
        next[target].type === 'conversation_id'
      ) {
        return prev
      }
      ;[next[idx], next[target]] = [next[target], next[idx]]
      return next
    })
  }

  const addParameter = () => {
    setParameters((prev) => [...prev, makeEmptyParameter()])
  }

  if (typeof document === 'undefined') return null

  return createPortal(
    <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity flex items-center justify-center z-[9999]">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-5xl mx-4 max-h-[92vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <h3 className="text-lg font-semibold">
            {isEditing ? 'Edit schema' : 'New schema'}
          </h3>
          <button
            onClick={onClose}
            disabled={isSubmitting}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Standard Voice QA"
              disabled={isSubmitting}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this schema used for?"
              rows={2}
              disabled={isSubmitting}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm font-medium text-gray-700">
                Parameters <span className="text-red-500">*</span>
              </p>
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<Plus className="h-4 w-4" />}
                onClick={addParameter}
                disabled={isSubmitting}
              >
                Add parameter
              </Button>
            </div>
            <div className="border border-gray-200 rounded-lg overflow-hidden">
              <div className="grid grid-cols-[24px_1fr_1fr_2fr_auto_auto] gap-2 bg-gray-50 px-3 py-2 text-xs font-medium text-gray-600 border-b border-gray-200">
                <div></div>
                <div>Name</div>
                <div>Type</div>
                <div>Description</div>
                <div>Required</div>
                <div></div>
              </div>
              <div className="divide-y divide-gray-100">
                {parameters.map((p, idx) => {
                  const isConversationId = p.type === 'conversation_id'
                  const isRecordingDate = p.type === 'recording_date'
                  const locked = isConversationId
                  const isSystemRequired = isConversationId || isRecordingDate
                  return (
                    <div
                      key={p.key}
                      className={`grid grid-cols-[24px_1fr_1fr_2fr_auto_auto] gap-2 items-center px-3 py-2 ${
                        locked ? 'bg-primary-50/30' : ''
                      }`}
                    >
                      <div className="flex flex-col items-center text-gray-400">
                        {locked ? (
                          <Lock className="h-3.5 w-3.5" />
                        ) : (
                          <>
                            <button
                              type="button"
                              onClick={() => moveParameter(idx, 'up')}
                              disabled={
                                isSubmitting ||
                                idx === 0 ||
                                idx - 1 === conversationIdIdx
                              }
                              className="leading-none text-[10px] disabled:opacity-30"
                              aria-label="Move up"
                            >
                              ▲
                            </button>
                            <GripVertical className="h-3.5 w-3.5" />
                            <button
                              type="button"
                              onClick={() => moveParameter(idx, 'down')}
                              disabled={
                                isSubmitting || idx === parameters.length - 1
                              }
                              className="leading-none text-[10px] disabled:opacity-30"
                              aria-label="Move down"
                            >
                              ▼
                            </button>
                          </>
                        )}
                      </div>
                      <div>
                        <input
                          type="text"
                          value={p.name}
                          onChange={(e) =>
                            updateParameter(idx, { name: e.target.value })
                          }
                          disabled={locked || isSubmitting}
                          placeholder="parameter_name"
                          className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50"
                        />
                      </div>
                      <div>
                        {locked ? (
                          <span className="inline-flex items-center px-2 py-1 text-xs font-medium rounded bg-primary-100 text-primary-700">
                            Conversation ID
                          </span>
                        ) : (
                          <select
                            value={p.type}
                            onChange={(e) => {
                              const nextType = e.target
                                .value as CallImportSchemaParameterType
                              updateParameter(idx, {
                                type: nextType,
                                is_required:
                                  nextType === 'recording_date'
                                    ? true
                                    : p.is_required,
                              })
                            }}
                            disabled={isSubmitting}
                            className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-primary-500"
                          >
                            {PARAMETER_TYPES.map((t) => (
                              <option key={t.value} value={t.value}>
                                {t.label}
                              </option>
                            ))}
                          </select>
                        )}
                      </div>
                      <div>
                        <input
                          type="text"
                          value={p.description}
                          onChange={(e) =>
                            updateParameter(idx, { description: e.target.value })
                          }
                          disabled={isSubmitting}
                          placeholder="optional helper text"
                          className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-primary-500"
                        />
                      </div>
                      <div className="text-center">
                        <input
                          type="checkbox"
                          checked={isSystemRequired ? true : p.is_required}
                          disabled={isSystemRequired || isSubmitting}
                          onChange={(e) =>
                            updateParameter(idx, {
                              is_required: e.target.checked,
                            })
                          }
                          className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50"
                        />
                      </div>
                      <div>
                        {!locked && (
                          <button
                            type="button"
                            onClick={() => removeParameter(idx)}
                            disabled={isSubmitting}
                            className="text-gray-400 hover:text-red-600 disabled:opacity-50"
                            aria-label="Delete parameter"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
            <p className="mt-1 text-xs text-gray-500">
              Every schema must include{' '}
              <code className="bg-gray-100 px-1 rounded">conversation_id</code>{' '}
              and required{' '}
              <code className="bg-gray-100 px-1 rounded">recording_date</code>{' '}
              — it identifies each imported row and cannot be removed.
            </p>
          </div>

          {errorMsg && (
            <div className="rounded-md bg-red-50 border border-red-200 p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-red-800">{errorMsg}</p>
              </div>
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={isSubmitting}
              className="flex-1"
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={handleSave}
              isLoading={isSubmitting}
              className="flex-1"
            >
              {isEditing ? 'Save changes' : 'Create schema'}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}

interface DeleteSchemaModalProps {
  schema: CallImportSchema | null
  isLoading: boolean
  error: string | null
  onConfirm: (force: boolean) => void
  onCancel: () => void
}

function DeleteSchemaModal({
  schema,
  isLoading,
  error,
  onConfirm,
  onCancel,
}: DeleteSchemaModalProps) {
  const [forceAcknowledged, setForceAcknowledged] = useState(false)

  useMemo(() => {
    if (schema) setForceAcknowledged(false)
  }, [schema?.id])

  if (!schema) return null
  if (typeof document === 'undefined') return null

  const usage = schema.usage_count
  const inUse = usage > 0
  const confirmDisabled =
    isLoading || (inUse && !forceAcknowledged)

  return createPortal(
    <div className="fixed inset-0 z-[10000] overflow-y-auto">
      <div
        className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
        onClick={() => {
          if (!isLoading) onCancel()
        }}
      />
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className="relative bg-white rounded-2xl shadow-xl max-w-md w-full p-6">
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2.5 rounded-full bg-[#fce8e6]">
              <AlertCircle className="w-5 h-5 text-[#ea4335]" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900">
              {inUse ? 'Force delete schema?' : 'Delete schema?'}
            </h3>
          </div>

          <div className="space-y-3 mb-5">
            <p className="text-sm text-gray-700">
              <span className="font-semibold">“{schema.name}”</span>{' '}
              {inUse
                ? `is currently used by ${usage} call import batch${usage === 1 ? '' : 'es'}.`
                : 'will be permanently removed. This cannot be undone.'}
            </p>

            {inUse && (
              <>
                <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 space-y-1.5">
                  <p className="font-medium">
                    What happens to those batches?
                  </p>
                  <ul className="list-disc pl-5 space-y-1">
                    <li>
                      They stay intact — rows, recordings, transcripts
                      and evaluations are untouched.
                    </li>
                    <li>
                      They are <em>detached</em> from this schema.
                      Already-imported batches keep working via their
                      snapshotted parameter mapping.
                    </li>
                    <li>
                      Any batch that was still staged (uploaded but not
                      yet imported) will need a new schema picked
                      before it can be imported.
                    </li>
                  </ul>
                </div>

                <label className="flex items-start gap-2 text-sm text-gray-800 cursor-pointer">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 rounded border-gray-300 text-red-600 focus:ring-red-500"
                    checked={forceAcknowledged}
                    onChange={(e) => setForceAcknowledged(e.target.checked)}
                    disabled={isLoading}
                  />
                  <span>
                    I understand {usage} batch
                    {usage === 1 ? '' : 'es'} will be detached from this
                    schema.
                  </span>
                </label>
              </>
            )}

            {error && (
              <div className="rounded-md bg-red-50 border border-red-200 p-3">
                <div className="flex items-start gap-2">
                  <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-red-800">{error}</p>
                </div>
              </div>
            )}
          </div>

          <div className="flex justify-end gap-3">
            <Button
              variant="ghost"
              onClick={onCancel}
              disabled={isLoading}
            >
              Cancel
            </Button>
            <button
              type="button"
              onClick={() => onConfirm(inUse)}
              disabled={confirmDisabled}
              className="px-4 py-2 rounded-full font-semibold transition-colors disabled:opacity-50 bg-[#fce8e6] hover:bg-[#fad2cf] text-[#c5221f]"
            >
              {isLoading
                ? 'Working…'
                : inUse
                  ? `Force delete (detach ${usage})`
                  : 'Delete'}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}

export default function CallImportSchemasPage() {
  const queryClient = useQueryClient()
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingSchema, setEditingSchema] = useState<CallImportSchema | null>(null)
  const [pendingDelete, setPendingDelete] = useState<CallImportSchema | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const { data: schemasResponse, isLoading } = useQuery({
    queryKey: ['call-import-schemas'],
    queryFn: () => apiClient.listCallImportSchemas(),
  })
  const schemas: CallImportSchema[] = schemasResponse?.items ?? []

  const deleteMutation = useMutation({
    mutationFn: ({
      schemaId,
      force,
    }: {
      schemaId: string
      force?: boolean
    }) => apiClient.deleteCallImportSchema(schemaId, { force }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import-schemas'] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      setPendingDelete(null)
      setDeleteError(null)
    },
    onError: (err: any) => {
      setDeleteError(
        err?.response?.data?.detail || err?.message || 'Failed to delete schema.',
      )
    },
  })

  const handleSaved = () => {
    queryClient.invalidateQueries({ queryKey: ['call-import-schemas'] })
    setEditorOpen(false)
    setEditingSchema(null)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Link
          to="/call-imports"
          className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Call Imports
        </Link>
        <Button
          variant="primary"
          size="sm"
          leftIcon={<Plus className="h-4 w-4" />}
          onClick={() => {
            setEditingSchema(null)
            setEditorOpen(true)
          }}
        >
          New schema
        </Button>
      </div>

      <div>
        <h1 className="text-2xl font-bold text-gray-900">Input Parameter Schemas</h1>
        <p className="mt-1 text-sm text-gray-600">
          Define reusable, typed Input Parameters that drive the Call Uploads
          mapping UI. Every schema must have a single{' '}
          <code className="bg-gray-100 px-1 rounded">conversation_id</code>{' '}
          parameter — that's the mandatory identifier on every imported row.
        </p>
      </div>

      <div className="bg-white shadow rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-6 text-center text-gray-500">Loading schemas...</div>
        ) : schemas.length === 0 ? (
          <div className="p-12 text-center text-gray-500">
            <p>No schemas yet.</p>
            <p className="text-xs mt-1">
              Use the "New schema" button to define your first one.
            </p>
          </div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Name
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Parameters
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Usage
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {schemas.map((schema) => (
                <tr key={schema.id} className="hover:bg-gray-50">
                  <td className="px-6 py-3">
                    <div className="text-sm font-medium text-gray-900">
                      {schema.name}
                    </div>
                    {schema.description && (
                      <div className="text-xs text-gray-500 mt-0.5">
                        {schema.description}
                      </div>
                    )}
                  </td>
                  <td className="px-6 py-3">
                    <div className="flex flex-wrap gap-1">
                      {schema.parameters.map((p) => (
                        <span
                          key={p.name}
                          className="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700 font-mono"
                          title={`${p.name} (${p.type})${
                            p.is_required ? ' · required' : ''
                          }`}
                        >
                          {p.name}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-6 py-3 text-sm text-gray-700">
                    {schema.usage_count > 0
                      ? `${schema.usage_count} import${
                          schema.usage_count === 1 ? '' : 's'
                        }`
                      : '—'}
                  </td>
                  <td className="px-6 py-3 text-right">
                    <div className="flex justify-end gap-3">
                      <button
                        type="button"
                        onClick={() => {
                          setEditingSchema(schema)
                          setEditorOpen(true)
                        }}
                        className="text-gray-400 hover:text-primary-600"
                        aria-label={`Edit ${schema.name}`}
                      >
                        <Edit3 className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setPendingDelete(schema)
                          setDeleteError(null)
                        }}
                        className="text-gray-400 hover:text-red-600"
                        aria-label={`Delete ${schema.name}`}
                        title={
                          schema.usage_count > 0
                            ? `In use by ${schema.usage_count} batch${
                                schema.usage_count === 1 ? '' : 'es'
                              } — you'll be asked to confirm a force delete that detaches them.`
                            : 'Delete schema'
                        }
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <SchemaEditor
        open={editorOpen}
        schema={editingSchema}
        onClose={() => {
          setEditorOpen(false)
          setEditingSchema(null)
        }}
        onSaved={handleSaved}
      />

      <DeleteSchemaModal
        schema={pendingDelete}
        isLoading={deleteMutation.isPending}
        error={deleteError}
        onConfirm={(force) => {
          if (pendingDelete) {
            deleteMutation.mutate({
              schemaId: pendingDelete.id,
              force,
            })
          }
        }}
        onCancel={() => {
          if (deleteMutation.isPending) return
          setPendingDelete(null)
          setDeleteError(null)
        }}
      />
    </div>
  )
}
