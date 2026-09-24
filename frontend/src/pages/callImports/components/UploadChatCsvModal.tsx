import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  FileSpreadsheet,
  FileText,
  MessageSquare,
  Upload,
  UploadCloud,
  X,
} from 'lucide-react'
import { apiClient } from '../../../lib/api'
import { itemsOf } from '../../../lib/safeData'
import Button from '../../../components/Button'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import type { CallImportSchema, CallImportTag } from '../../../types/api'

interface UploadChatCsvModalProps {
  open: boolean
  onClose: () => void
  initialSchemaId?: string | null
}

const MAX_BYTES = 15 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['.csv', '.xlsx', '.xlsm'] as const
const ACCEPT_ATTR =
  '.csv,text/csv,.xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const CHAT_SCHEMA_NAME = 'Chat transcript (post-prod)'

function renderModal(content: ReactNode) {
  if (typeof document === 'undefined') return null
  return createPortal(content, document.body)
}

function getExtension(filename: string): string {
  const idx = filename.lastIndexOf('.')
  return idx >= 0 ? filename.slice(idx).toLowerCase() : ''
}

function preflight(file: File): string | null {
  const ext = getExtension(file.name)
  if (!ALLOWED_EXTENSIONS.includes(ext as (typeof ALLOWED_EXTENSIONS)[number])) {
    return `File must be one of: ${ALLOWED_EXTENSIONS.join(', ')}`
  }
  if (file.size > MAX_BYTES) {
    return 'File exceeds 15 MB; please split it.'
  }
  return null
}

export default function UploadChatCsvModal({
  open,
  onClose,
  initialSchemaId,
}: UploadChatCsvModalProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [dataset, setDataset] = useState('')
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([])
  const [selectedSchemaId, setSelectedSchemaId] = useState<string>('')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)

  const { data: existingDatasets = [] } = useQuery({
    queryKey: ['call-import-datasets', activeWorkspaceId],
    queryFn: () => apiClient.listCallImportDatasets(),
    enabled: open,
  })

  const { data: allTags = [] } = useQuery({
    queryKey: ['call-import-tags', activeWorkspaceId],
    queryFn: () => apiClient.listCallImportTags(),
    enabled: open,
  })

  const { data: schemasResponse } = useQuery({
    queryKey: ['call-import-schemas', activeWorkspaceId],
    queryFn: () => apiClient.listCallImportSchemas(),
    enabled: open,
  })
  const schemas = useMemo(
    () => itemsOf<CallImportSchema>(schemasResponse),
    [schemasResponse],
  )

  const chatSchema = useMemo(
    () => schemas.find((s) => s.name === CHAT_SCHEMA_NAME),
    [schemas],
  )

  useEffect(() => {
    if (!open) return
    setSelectedFile(null)
    setFileError(null)
    setDataset('')
    setSelectedTagIds([])
    setSelectedSchemaId(initialSchemaId || chatSchema?.id || '')
    setSubmitError(null)
    setIsDragOver(false)
  }, [open, initialSchemaId, chatSchema?.id])

  const handleFile = (file: File | null) => {
    if (!file) {
      setSelectedFile(null)
      setFileError(null)
      return
    }
    const err = preflight(file)
    if (err) {
      setFileError(err)
      setSelectedFile(null)
      return
    }
    setFileError(null)
    setSelectedFile(file)
  }

  const createMutation = useMutation({
    mutationFn: () => {
      if (!selectedFile) {
        throw new Error('Pick a file first.')
      }
      return apiClient.createCallImport(selectedFile, {
        dataset: dataset.trim(),
        tagIds: selectedTagIds,
        schemaId: selectedSchemaId || chatSchema?.id || null,
        contentModality: 'chat',
      })
    },
    onSuccess: (created) => {
      setSubmitError(null)
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      queryClient.invalidateQueries({ queryKey: ['chat-imports'] })
      queryClient.invalidateQueries({ queryKey: ['call-import-datasets'] })
      onClose()
      navigate(`/call-imports/${created.id}`)
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err as Error)?.message
      setSubmitError(String(detail || 'Failed to upload file.'))
    },
  })

  const canSubmit = !!selectedFile && !!dataset.trim() && !createMutation.isPending

  if (!open) return null

  const ext = selectedFile ? getExtension(selectedFile.name) : ''
  const isExcel = ext === '.xlsx' || ext === '.xlsm'

  return renderModal(
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden />
      <div
        className="relative w-full max-w-lg rounded-xl bg-white shadow-xl border border-gray-200"
        role="dialog"
        aria-labelledby="upload-chat-import-title"
      >
        <div className="flex items-start justify-between border-b border-gray-100 px-5 py-4">
          <div>
            <h2 id="upload-chat-import-title" className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <MessageSquare className="h-5 w-5 text-primary-600" />
              Upload chat transcripts
            </h2>
            <p className="text-sm text-gray-500 mt-1">
              CSV or Excel with conversation id and transcript columns. Same mapping flow as call imports.
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4 max-h-[70vh] overflow-y-auto">
          {!chatSchema && !selectedSchemaId ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              Chat schema not found. Open a chat agent and use{' '}
              <span className="font-medium">Open chat import setup</span> first, or pick a schema below.
            </div>
          ) : null}

          <div
            onDragOver={(e) => {
              e.preventDefault()
              setIsDragOver(true)
            }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={(e) => {
              e.preventDefault()
              setIsDragOver(false)
              handleFile(e.dataTransfer.files?.[0] ?? null)
            }}
            className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
              isDragOver ? 'border-primary-400 bg-primary-50' : 'border-gray-200'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT_ATTR}
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
            />
            {selectedFile ? (
              <div className="flex flex-col items-center gap-2">
                {isExcel ? (
                  <FileSpreadsheet className="h-10 w-10 text-emerald-600" />
                ) : (
                  <FileText className="h-10 w-10 text-blue-600" />
                )}
                <p className="text-sm font-medium text-gray-900">{selectedFile.name}</p>
                <Button variant="ghost" size="sm" onClick={() => fileInputRef.current?.click()}>
                  Change file
                </Button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex flex-col items-center gap-2 w-full text-gray-600 hover:text-gray-900"
              >
                <UploadCloud className="h-10 w-10" />
                <span className="text-sm font-medium">Drop file or click to browse</span>
              </button>
            )}
            {fileError ? (
              <p className="mt-2 text-sm text-red-600 flex items-center justify-center gap-1">
                <AlertCircle className="h-4 w-4" />
                {fileError}
              </p>
            ) : null}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Dataset</label>
            <input
              list="chat-import-datasets"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
              placeholder="e.g. prod-chat-logs-2025-09"
            />
            <datalist id="chat-import-datasets">
              {existingDatasets.map((d) => (
                <option key={d} value={d} />
              ))}
            </datalist>
          </div>

          {schemas.length > 0 ? (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Schema</label>
              <select
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                value={selectedSchemaId}
                onChange={(e) => setSelectedSchemaId(e.target.value)}
              >
                <option value="">Auto (chat transcript schema)</option>
                {schemas.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          {allTags.length > 0 ? (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Tags</label>
              <div className="flex flex-wrap gap-2">
                {allTags.map((tag: CallImportTag) => {
                  const checked = selectedTagIds.includes(tag.id)
                  return (
                    <button
                      key={tag.id}
                      type="button"
                      onClick={() =>
                        setSelectedTagIds((prev) =>
                          checked ? prev.filter((id) => id !== tag.id) : [...prev, tag.id],
                        )
                      }
                      className={`rounded-full px-3 py-1 text-xs font-medium border ${
                        checked
                          ? 'border-primary-600 bg-primary-50 text-primary-800'
                          : 'border-gray-200 text-gray-600'
                      }`}
                    >
                      {tag.name}
                    </button>
                  )
                })}
              </div>
            </div>
          ) : null}

          {submitError ? (
            <p className="text-sm text-red-600 flex items-center gap-1">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {submitError}
            </p>
          ) : null}
        </div>

        <div className="flex items-center justify-between border-t border-gray-100 px-5 py-4">
          <Link to="/call-imports/schemas" className="text-xs text-gray-500 hover:text-gray-700">
            Manage schemas
          </Link>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button
              variant="primary"
              disabled={!canSubmit}
              isLoading={createMutation.isPending}
              leftIcon={<Upload className="h-4 w-4" />}
              onClick={() => createMutation.mutate()}
            >
              Upload
            </Button>
          </div>
        </div>
      </div>
    </div>,
  )
}
