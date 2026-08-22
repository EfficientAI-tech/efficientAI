import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, FileAudio, Upload, UploadCloud, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { useToast } from '../../hooks/useToast'
import Button from '../../components/Button'
import { defaultNameFromFilename } from './useAmbientPreview'

interface UploadAmbientNoiseModalProps {
  open: boolean
  onClose: () => void
}

const MAX_BYTES = 10 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['.wav', '.mp3', '.ogg', '.m4a', '.flac'] as const
const ACCEPT_ATTR = '.wav,.mp3,.ogg,.m4a,.flac,audio/wav,audio/mpeg,audio/ogg,audio/flac,audio/mp4'

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
    return 'File exceeds 10 MB.'
  }
  return null
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}

export default function UploadAmbientNoiseModal({ open, onClose }: UploadAmbientNoiseModalProps) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [displayName, setDisplayName] = useState('')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)

  useEffect(() => {
    if (!open) return
    setSelectedFile(null)
    setFileError(null)
    setDisplayName('')
    setSubmitError(null)
    setIsDragOver(false)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }, [open])

  const handleFile = (file: File | null) => {
    if (!file) {
      setSelectedFile(null)
      setFileError(null)
      return
    }

    const error = validateFile(file)
    if (error) {
      setSelectedFile(null)
      setFileError(`${file.name}: ${error}`)
      return
    }

    setSelectedFile(file)
    setFileError(null)
    setDisplayName(defaultNameFromFilename(file.name))
  }

  const handleFiles = (fileList: FileList | File[] | null) => {
    const file = Array.from(fileList || [])[0] ?? null
    handleFile(file)
  }

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!selectedFile) {
        throw new Error('Pick an audio file first.')
      }
      const trimmed = displayName.trim()
      if (!trimmed) {
        throw new Error('Enter a display name.')
      }
      return apiClient.uploadAmbientLibraryAsset(selectedFile, trimmed)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ambient-library'] })
      setSubmitError(null)
      showToast('Background noise uploaded', 'success')
      onClose()
    },
    onError: (err: any) => {
      setSubmitError(err?.response?.data?.detail || err?.message || 'Failed to upload audio.')
    },
  })

  const canSubmit =
    !!selectedFile &&
    !fileError &&
    !!displayName.trim() &&
    !uploadMutation.isPending

  if (!open) return null

  return renderModal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Upload Background Noise</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Choose an ambient loop and give it a display name for your workspace library.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={uploadMutation.isPending}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
            aria-label="Close upload modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 py-5 overflow-y-auto flex-1 space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Audio file <span className="text-red-500">*</span>
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
                  : selectedFile
                    ? 'border-green-300 bg-green-50'
                    : 'border-gray-300 hover:border-gray-400 bg-gray-50'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPT_ATTR}
                onChange={(e) => handleFiles(e.target.files)}
                className="hidden"
              />
              {selectedFile ? (
                <div className="text-sm text-gray-800">
                  <FileAudio className="h-8 w-8 mx-auto mb-2 text-green-600" />
                  <p className="font-medium truncate" title={selectedFile.name}>
                    {selectedFile.name}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">{formatBytes(selectedFile.size)}</p>
                  <p className="text-xs text-primary-600 mt-2">Click or drop to replace</p>
                </div>
              ) : (
                <div className="text-sm text-gray-600">
                  <UploadCloud className="h-8 w-8 mx-auto mb-2 text-gray-400" />
                  <p>
                    Drag an audio file here, or{' '}
                    <span className="text-primary-600 font-medium">browse</span>
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {ALLOWED_EXTENSIONS.join(', ')} up to 10 MB
                  </p>
                </div>
              )}
            </div>

            {fileError ? (
              <div className="mt-2 rounded-md bg-red-50 border border-red-200 p-3 text-xs text-red-700">
                {fileError}
              </div>
            ) : null}
          </div>

          <div>
            <label htmlFor="ambient-display-name" className="block text-sm font-medium text-gray-700 mb-1">
              Display name <span className="text-red-500">*</span>
            </label>
            <input
              id="ambient-display-name"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="e.g. Busy cafe"
              disabled={!selectedFile}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 disabled:bg-gray-100 disabled:text-gray-500"
            />
            <p className="mt-1 text-xs text-gray-500">
              This name appears when assigning background noise to personas.
            </p>
          </div>

          {submitError ? (
            <div className="rounded-md bg-red-50 border border-red-200 p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-red-800">{submitError}</p>
              </div>
            </div>
          ) : null}
        </div>

        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-3">
          <Button variant="outline" onClick={onClose} disabled={uploadMutation.isPending}>
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
