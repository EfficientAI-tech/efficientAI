import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  FileAudio,
  Upload,
  UploadCloud,
  X,
} from 'lucide-react'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import type { CallImportTag } from '../../../types/api'

interface UploadAudioModalProps {
  open: boolean
  onClose: () => void
}

const MAX_BYTES = 500 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['.wav', '.mp3', '.flac', '.m4a'] as const
const ACCEPT_ATTR = '.wav,.mp3,.flac,.m4a,audio/wav,audio/mpeg,audio/flac,audio/mp4'

function renderModal(content: ReactNode) {
  if (typeof document === 'undefined') return null
  return createPortal(content, document.body)
}

function getExtension(filename: string): string {
  const idx = filename.lastIndexOf('.')
  return idx >= 0 ? filename.slice(idx).toLowerCase() : ''
}

function validateFile(file: File): string | null {
  const ext = getExtension(file.name)
  if (!ALLOWED_EXTENSIONS.includes(ext as (typeof ALLOWED_EXTENSIONS)[number])) {
    return `Unsupported format. Use ${ALLOWED_EXTENSIONS.join(', ')}.`
  }
  if (file.size <= 0) {
    return 'File is empty.'
  }
  if (file.size > MAX_BYTES) {
    return 'File exceeds 500 MB.'
  }
  return null
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  const mb = kb / 1024
  if (mb < 1024) return `${mb.toFixed(1)} MB`
  return `${(mb / 1024).toFixed(1)} GB`
}

export default function UploadAudioModal({ open, onClose }: UploadAudioModalProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [fileErrors, setFileErrors] = useState<string[]>([])
  const [dataset, setDataset] = useState('')
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([])
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

  useEffect(() => {
    if (!open) return
    setSelectedFiles([])
    setFileErrors([])
    setDataset('')
    setSelectedTagIds([])
    setSubmitError(null)
    setIsDragOver(false)
  }, [open])

  const handleFiles = (fileList: FileList | File[] | null) => {
    const files = Array.from(fileList || [])
    if (files.length === 0) {
      setSelectedFiles([])
      setFileErrors([])
      return
    }

    const errors: string[] = []
    const valid: File[] = []
    files.forEach((file) => {
      const error = validateFile(file)
      if (error) {
        errors.push(`${file.name}: ${error}`)
      } else {
        valid.push(file)
      }
    })
    setSelectedFiles(valid)
    setFileErrors(errors)
  }

  const uploadMutation = useMutation({
    mutationFn: () => {
      if (selectedFiles.length === 0) {
        throw new Error('Pick at least one audio file first.')
      }
      return apiClient.uploadCallImportAudio(selectedFiles, {
        dataset: dataset.trim(),
        tagIds: selectedTagIds,
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
        err?.response?.data?.detail || err?.message || 'Failed to upload audio.',
      )
    },
  })

  const totalBytes = selectedFiles.reduce((sum, file) => sum + file.size, 0)
  const canSubmit =
    selectedFiles.length > 0 &&
    fileErrors.length === 0 &&
    !!dataset.trim() &&
    !uploadMutation.isPending

  if (!open) return null

  return renderModal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              Upload Call Audio
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Add one or more recordings directly. File names become call IDs.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={uploadMutation.isPending}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
            aria-label="Close audio upload modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 py-5 overflow-y-auto flex-1 space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Recordings <span className="text-red-500">*</span>
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
                handleFiles(e.dataTransfer.files)
              }}
              className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition ${
                isDragOver
                  ? 'border-primary-400 bg-primary-50'
                  : selectedFiles.length > 0
                    ? 'border-green-300 bg-green-50'
                    : 'border-gray-300 hover:border-gray-400 bg-gray-50'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPT_ATTR}
                multiple
                onChange={(e) => handleFiles(e.target.files)}
                className="hidden"
              />
              {selectedFiles.length > 0 ? (
                <div className="text-sm text-gray-800">
                  <FileAudio className="h-8 w-8 mx-auto mb-2 text-green-600" />
                  <p className="font-medium">
                    {selectedFiles.length} file{selectedFiles.length === 1 ? '' : 's'} selected
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    Total size {formatBytes(totalBytes)}
                  </p>
                </div>
              ) : (
                <div className="text-sm text-gray-600">
                  <UploadCloud className="h-8 w-8 mx-auto mb-2 text-gray-400" />
                  <p>
                    Drag audio files here, or{' '}
                    <span className="text-primary-600 font-medium">browse</span>
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {ALLOWED_EXTENSIONS.join(', ')} up to 500 MB each
                  </p>
                </div>
              )}
            </div>

            {selectedFiles.length > 0 && (
              <div className="mt-3 max-h-36 overflow-y-auto rounded-md border border-gray-200 divide-y divide-gray-100">
                {selectedFiles.map((file) => (
                  <div key={`${file.name}-${file.size}-${file.lastModified}`} className="px-3 py-2 flex items-center justify-between gap-3">
                    <div className="min-w-0 flex items-center gap-2">
                      <FileAudio className="h-4 w-4 text-gray-400 flex-shrink-0" />
                      <span className="text-sm text-gray-800 truncate">{file.name}</span>
                    </div>
                    <span className="text-xs text-gray-500 flex-shrink-0">
                      {formatBytes(file.size)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {fileErrors.length > 0 && (
              <div className="mt-2 rounded-md bg-red-50 border border-red-200 p-3 text-xs text-red-700 space-y-1">
                {fileErrors.map((error) => (
                  <p key={error}>{error}</p>
                ))}
              </div>
            )}
          </div>

          <div>
            <label
              htmlFor="audio-upload-dataset"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Dataset <span className="text-red-500">*</span>
            </label>
            <input
              id="audio-upload-dataset"
              type="text"
              list="audio-upload-dataset-suggestions"
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
              placeholder="e.g. October prod calls"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
            />
            <datalist id="audio-upload-dataset-suggestions">
              {existingDatasets.map((d) => (
                <option key={d} value={d} />
              ))}
            </datalist>
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
            disabled={uploadMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            leftIcon={<Upload className="h-4 w-4" />}
            onClick={() => uploadMutation.mutate()}
            isLoading={uploadMutation.isPending}
            disabled={!canSubmit}
          >
            Upload audio
          </Button>
        </div>
      </div>
    </div>,
  )
}
