import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  FileSpreadsheet,
  FileText,
  Upload,
  UploadCloud,
  X,
} from 'lucide-react'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import type { CallImportTag } from '../../../types/api'

interface UploadCsvModalProps {
  open: boolean
  onClose: () => void
}

const MAX_BYTES = 10 * 1024 * 1024

const ALLOWED_EXTENSIONS = ['.csv', '.xlsx', '.xlsm'] as const
const ACCEPT_ATTR =
  '.csv,text/csv,.xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

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
    return 'File exceeds 10 MB; please split it.'
  }
  return null
}

/**
 * Single-step upload modal for the staged call-import flow.
 *
 * The user picks a file + dataset (+ optional tags + optional schema
 * pre-pick) and we hit ``POST /call-imports`` which persists the file
 * to S3 and creates a ``status='uploaded'`` batch. The actual mapping
 * + import steps happen on the resulting detail page, so this modal
 * intentionally stays short — no preview, no column-mapping table.
 */
export default function UploadCsvModal({ open, onClose }: UploadCsvModalProps) {
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
    () => schemasResponse?.items ?? [],
    [schemasResponse],
  )

  useEffect(() => {
    if (!open) return
    // Reset every time the modal opens so a closed-and-reopened flow
    // doesn't surface stale state from the previous attempt.
    setSelectedFile(null)
    setFileError(null)
    setDataset('')
    setSelectedTagIds([])
    setSelectedSchemaId('')
    setSubmitError(null)
    setIsDragOver(false)
  }, [open])

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
        schemaId: selectedSchemaId || null,
      })
    },
    onSuccess: (created) => {
      setSubmitError(null)
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      queryClient.invalidateQueries({ queryKey: ['call-import-datasets'] })
      onClose()
      navigate(`/call-imports/${created.id}`)
    },
    onError: (err: any) => {
      setSubmitError(
        err?.response?.data?.detail || err?.message || 'Failed to upload file.',
      )
    },
  })

  const canSubmit =
    !!selectedFile &&
    !!dataset.trim() &&
    !createMutation.isPending

  if (!open) return null

  const ext = selectedFile ? getExtension(selectedFile.name) : ''
  const isExcel = ext === '.xlsx' || ext === '.xlsm'

  return renderModal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              Upload Call Recordings
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Stage a CSV / Excel file. You'll map columns and start the
              import on the next page.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={createMutation.isPending}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
            aria-label="Close upload modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 py-5 overflow-y-auto flex-1 space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Source File <span className="text-red-500">*</span>
            </label>
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                setIsDragOver(true)
              }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setIsDragOver(false)
                const file = e.dataTransfer.files?.[0]
                if (file) handleFile(file)
              }}
              className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition ${
                isDragOver
                  ? 'border-primary-400 bg-primary-50'
                  : selectedFile
                    ? 'border-green-300 bg-green-50'
                    : 'border-gray-300 hover:border-gray-400 bg-gray-50'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPT_ATTR}
                onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
                className="hidden"
              />
              {selectedFile ? (
                <div className="flex items-center justify-center gap-2 text-sm text-gray-800">
                  {isExcel ? (
                    <FileSpreadsheet className="h-5 w-5 text-green-600" />
                  ) : (
                    <FileText className="h-5 w-5 text-green-600" />
                  )}
                  <span className="font-medium">{selectedFile.name}</span>
                  <span className="text-xs text-gray-500">
                    ({(selectedFile.size / 1024).toFixed(1)} KB)
                  </span>
                </div>
              ) : (
                <div className="text-sm text-gray-600">
                  <UploadCloud className="h-8 w-8 mx-auto mb-2 text-gray-400" />
                  <p>
                    Drag a file here, or{' '}
                    <span className="text-primary-600 font-medium">browse</span>
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {ALLOWED_EXTENSIONS.join(', ')} · up to 10 MB
                  </p>
                </div>
              )}
            </div>
            {fileError && (
              <p className="mt-2 text-xs text-red-600">{fileError}</p>
            )}
          </div>

          <div>
            <label
              htmlFor="upload-dataset"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Dataset <span className="text-red-500">*</span>
            </label>
            <input
              id="upload-dataset"
              type="text"
              list="upload-dataset-suggestions"
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
              placeholder="e.g. October prod calls"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
            />
            <datalist id="upload-dataset-suggestions">
              {existingDatasets.map((d) => (
                <option key={d} value={d} />
              ))}
            </datalist>
            <p className="mt-1 text-xs text-gray-500">
              Used as a high-level filter on the Call Imports list. You can
              edit it later from the detail page.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Tags
            </label>
            {allTags.length === 0 ? (
              <p className="text-xs text-gray-500">
                No tags created yet.{' '}
                <Link
                  to="/call-imports/tags"
                  className="text-primary-600 hover:text-primary-700 underline"
                  onClick={onClose}
                >
                  Create tags
                </Link>
                .
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {allTags.map((tag: CallImportTag) => {
                  const active = selectedTagIds.includes(tag.id)
                  return (
                    <button
                      key={tag.id}
                      type="button"
                      onClick={() =>
                        setSelectedTagIds((prev) =>
                          prev.includes(tag.id)
                            ? prev.filter((t) => t !== tag.id)
                            : [...prev, tag.id],
                        )
                      }
                      className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                        active
                          ? 'bg-primary-600 border-primary-600 text-white'
                          : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
                      }`}
                      style={
                        !active && tag.color
                          ? { borderColor: tag.color, color: tag.color }
                          : undefined
                      }
                    >
                      {tag.name}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Input Parameter Schema{' '}
              <span className="text-xs text-gray-400 font-normal">
                (optional pre-pick)
              </span>
            </label>
            {schemas.length === 0 ? (
              <div className="rounded-md bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800 space-y-2">
                <p>
                  No Input Parameter schemas in this workspace yet — you can
                  still upload now and create one before mapping.
                </p>
                <Link
                  to="/call-imports/schemas"
                  className="inline-block font-medium text-amber-900 underline hover:text-amber-700"
                  onClick={onClose}
                >
                  Create a schema &rarr;
                </Link>
              </div>
            ) : (
              <select
                value={selectedSchemaId}
                onChange={(e) => setSelectedSchemaId(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
              >
                <option value="">Pick later</option>
                {schemas.map((schema) => (
                  <option key={schema.id} value={schema.id}>
                    {schema.name} · {schema.parameters.length} params
                  </option>
                ))}
              </select>
            )}
            <p className="mt-1 text-xs text-gray-500">
              You'll be able to change the schema while mapping columns on
              the next page.
            </p>
          </div>

          {submitError && (
            <div className="rounded-md bg-red-50 border border-red-200 p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-red-800">{submitError}</p>
              </div>
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-3">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={createMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            leftIcon={<Upload className="h-4 w-4" />}
            onClick={() => createMutation.mutate()}
            isLoading={createMutation.isPending}
            disabled={!canSubmit}
          >
            Upload &amp; continue
          </Button>
        </div>
      </div>
    </div>,
  )
}
