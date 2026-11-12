import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, FileText, Upload, UploadCloud, X } from 'lucide-react'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'
import type { KnowledgeBaseSummary } from '../knowledgeBaseTypes'
import KnowledgeBaseEmbeddingPicker, {
  DEFAULT_KB_EMBEDDING,
  eligibleEmbeddingProviders,
  resolveDefaultKnowledgeBaseEmbedding,
  type KnowledgeBaseEmbeddingValue,
} from './KnowledgeBaseEmbeddingPicker'

const ALLOWED_EXTENSIONS = ['pdf', 'txt', 'md', 'docx'] as const
const ACCEPT_ATTR = '.pdf,.txt,.md,.docx'
const MAX_BYTES = 25 * 1024 * 1024

interface UploadKnowledgeBaseModalProps {
  open: boolean
  onClose: () => void
  /** Upload into an existing knowledge base (detail page). */
  appendToKnowledgeBaseId?: string
  appendToKnowledgeBaseName?: string
  /** Current embedding on the base when appending documents. */
  appendKnowledgeBaseEmbedding?: KnowledgeBaseEmbeddingValue
}

function renderModal(content: ReactNode) {
  if (typeof document === 'undefined') return null
  return createPortal(content, document.body)
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function validateFile(file: File): string | null {
  const ext = file.name.includes('.') ? file.name.split('.').pop()?.toLowerCase() : ''
  if (!ext || !ALLOWED_EXTENSIONS.includes(ext as (typeof ALLOWED_EXTENSIONS)[number])) {
    return `Unsupported type (use ${ALLOWED_EXTENSIONS.join(', ')})`
  }
  if (file.size <= 0) return 'File is empty'
  if (file.size > MAX_BYTES) return `Exceeds ${formatBytes(MAX_BYTES)}`
  return null
}

function embeddingEquals(a: KnowledgeBaseEmbeddingValue, b: KnowledgeBaseEmbeddingValue): boolean {
  return (
    a.provider === b.provider &&
    a.model === b.model &&
    (a.credential_id ?? null) === (b.credential_id ?? null)
  )
}

export default function UploadKnowledgeBaseModal({
  open,
  onClose,
  appendToKnowledgeBaseId,
  appendToKnowledgeBaseName,
  appendKnowledgeBaseEmbedding,
}: UploadKnowledgeBaseModalProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const isAppendMode = Boolean(appendToKnowledgeBaseId)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [embedding, setEmbedding] = useState<KnowledgeBaseEmbeddingValue>({
    provider: 'openai',
    model: 'text-embedding-3-small',
    credential_id: null,
  })
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [fileErrors, setFileErrors] = useState<string[]>([])
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<{
    uploaded: number
    total: number
    fileName: string
  } | null>(null)

  const { data: existingBases = [] } = useQuery({
    queryKey: ['knowledge-bases'],
    queryFn: () => apiClient.listKnowledgeBases(),
    enabled: open && !isAppendMode,
  })

  const { data: embeddingConfig } = useQuery({
    queryKey: ['knowledge-base-embedding-config'],
    queryFn: () => apiClient.getKnowledgeBaseEmbeddingConfig(),
    enabled: open,
  })

  const { data: aiProviders = [] } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
    enabled: open,
  })

  const hasEligibleEmbedding =
    eligibleEmbeddingProviders(embeddingConfig?.providers, aiProviders).length > 0

  useEffect(() => {
    if (!open) return
    setName('')
    setDescription('')
    setEmbedding(DEFAULT_KB_EMBEDDING)
    setSelectedFiles([])
    setFileErrors([])
    setSubmitError(null)
    setIsDragOver(false)
    setUploadProgress(null)
  }, [open])

  useEffect(() => {
    if (!open || !isAppendMode || !appendKnowledgeBaseEmbedding) return
    setEmbedding(appendKnowledgeBaseEmbedding)
  }, [
    open,
    isAppendMode,
    appendKnowledgeBaseEmbedding?.provider,
    appendKnowledgeBaseEmbedding?.model,
    appendKnowledgeBaseEmbedding?.credential_id,
  ])

  useEffect(() => {
    if (!open || isAppendMode) return
    const resolved = resolveDefaultKnowledgeBaseEmbedding(
      embeddingConfig?.providers,
      aiProviders,
    )
    if (resolved) setEmbedding(resolved)
  }, [open, isAppendMode, embeddingConfig?.providers, aiProviders])

  const handleFiles = (fileList: FileList | File[] | null) => {
    const incoming = Array.from(fileList || [])
    if (incoming.length === 0) {
      setSelectedFiles([])
      setFileErrors([])
      return
    }
    const errors: string[] = []
    const valid: File[] = []
    incoming.forEach((file) => {
      const err = validateFile(file)
      if (err) errors.push(`${file.name}: ${err}`)
      else valid.push(file)
    })
    setSelectedFiles((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}-${f.size}-${f.lastModified}`))
      const merged = [...prev]
      valid.forEach((f) => {
        const key = `${f.name}-${f.size}-${f.lastModified}`
        if (!seen.has(key)) {
          seen.add(key)
          merged.push(f)
        }
      })
      return merged
    })
    setFileErrors(errors)
  }

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (selectedFiles.length === 0) {
        throw new Error('Select at least one document.')
      }
      let kbId = appendToKnowledgeBaseId
      if (!kbId) {
        const trimmed = name.trim()
        if (!trimmed) {
          throw new Error('Knowledge base name is required.')
        }
        const created = await apiClient.createKnowledgeBase({
          name: trimmed,
          description: description.trim() || undefined,
          embedding_provider: embedding.provider,
          embedding_model: embedding.model,
          embedding_credential_id: embedding.credential_id,
        })
        kbId = created.id as string
      } else if (
        appendKnowledgeBaseEmbedding &&
        !embeddingEquals(embedding, appendKnowledgeBaseEmbedding)
      ) {
        await apiClient.updateKnowledgeBase(kbId, {
          embedding_provider: embedding.provider,
          embedding_model: embedding.model,
          embedding_credential_id: embedding.credential_id,
        })
      }
      setUploadProgress({ uploaded: 0, total: selectedFiles.length, fileName: '' })
      const result = await apiClient.uploadKnowledgeDocuments(kbId, selectedFiles, {
        onProgress: setUploadProgress,
      })
      return { kbId, ...result }
    },
    onSuccess: ({ kbId, uploaded, failed }) => {
      setUploadProgress(null)
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge-base', kbId] })
      if (failed.length > 0 && uploaded === 0) {
        setSubmitError(failed.map((f) => `${f.fileName}: ${f.error}`).join('\n'))
        return
      }
      onClose()
      if (!isAppendMode) {
        navigate(`/knowledge-bases/${kbId}`)
      }
    },
    onError: (err: { response?: { data?: { detail?: string } }; message?: string }) => {
      setUploadProgress(null)
      setSubmitError(
        err?.response?.data?.detail?.toString() || err?.message || 'Upload failed.',
      )
    },
  })

  const totalBytes = selectedFiles.reduce((sum, f) => sum + f.size, 0)
  const canSubmit =
    selectedFiles.length > 0 &&
    hasEligibleEmbedding &&
    (isAppendMode || name.trim().length > 0) &&
    !uploadMutation.isPending

  if (!open) return null

  return renderModal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              {isAppendMode ? 'Upload documents' : 'Upload knowledge base'}
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {isAppendMode
                ? `Add files to ${appendToKnowledgeBaseName?.trim() || 'this knowledge base'}. Indexing runs in the background.`
                : 'Name your knowledge base and add one or more documents (PDF, TXT, MD, DOCX).'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={uploadMutation.isPending}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 py-5 overflow-y-auto flex-1 space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Embedding</label>
            <KnowledgeBaseEmbeddingPicker value={embedding} onChange={setEmbedding} />
            {isAppendMode &&
              appendKnowledgeBaseEmbedding &&
              !embeddingEquals(embedding, appendKnowledgeBaseEmbedding) && (
                <p className="text-xs text-amber-700 mt-2">
                  Changing embedding re-indexes all documents in this knowledge base.
                </p>
              )}
          </div>

          {!isAppendMode && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Knowledge base name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  list="kb-existing-names"
                  placeholder="e.g. Product FAQ, Support policies"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                />
                {existingBases.length > 0 && (
                  <datalist id="kb-existing-names">
                    {(existingBases as KnowledgeBaseSummary[]).map((kb) => (
                      <option key={kb.id} value={kb.name} />
                    ))}
                  </datalist>
                )}
                <p className="text-xs text-gray-500 mt-1">
                  Like a call-import dataset name — use a new name to create a library, or open an
                  existing base from the list to add more files.
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Description <span className="text-gray-400">(optional)</span>
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                  placeholder="What these documents are for"
                />
              </div>
            </>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Documents <span className="text-red-500">*</span>
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
                  <Upload className="h-8 w-8 mx-auto mb-2 text-green-600" />
                  <p className="font-medium">
                    {selectedFiles.length} file{selectedFiles.length === 1 ? '' : 's'} selected
                  </p>
                  <p className="text-xs text-gray-500 mt-1">Total {formatBytes(totalBytes)}</p>
                </div>
              ) : (
                <div className="text-sm text-gray-600">
                  <UploadCloud className="h-8 w-8 mx-auto mb-2 text-gray-400" />
                  <p>
                    Drag files here, or{' '}
                    <span className="text-primary-600 font-medium">browse</span>
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {ALLOWED_EXTENSIONS.join(', ')} · up to {formatBytes(MAX_BYTES)} each
                  </p>
                </div>
              )}
            </div>

            {selectedFiles.length > 0 && (
              <div className="mt-3 max-h-36 overflow-y-auto rounded-md border border-gray-200 divide-y divide-gray-100">
                {selectedFiles.map((file) => (
                  <div
                    key={`${file.name}-${file.size}-${file.lastModified}`}
                    className="px-3 py-2 flex items-center justify-between gap-3"
                  >
                    <div className="min-w-0 flex items-center gap-2">
                      <FileText className="h-4 w-4 text-gray-400 shrink-0" />
                      <span className="text-sm text-gray-800 truncate">{file.name}</span>
                    </div>
                    <span className="text-xs text-gray-500 shrink-0">{formatBytes(file.size)}</span>
                  </div>
                ))}
              </div>
            )}

            {fileErrors.length > 0 && (
              <ul className="mt-2 text-xs text-red-600 space-y-0.5">
                {fileErrors.map((msg) => (
                  <li key={msg}>{msg}</li>
                ))}
              </ul>
            )}
          </div>

          {submitError && (
            <div className="flex gap-2 text-sm text-red-700 bg-red-50 border border-red-100 rounded-lg p-3">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <pre className="whitespace-pre-wrap font-sans text-xs">{submitError}</pre>
            </div>
          )}

          {uploadProgress && uploadMutation.isPending && (
            <p className="text-sm text-gray-600">
              Uploading {Math.min(uploadProgress.uploaded + 1, uploadProgress.total)} of{' '}
              {uploadProgress.total}
              {uploadProgress.fileName ? `: ${uploadProgress.fileName}` : ''}
            </p>
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
          <Button variant="secondary" onClick={onClose} disabled={uploadMutation.isPending}>
            Cancel
          </Button>
          <Button onClick={() => uploadMutation.mutate()} disabled={!canSubmit} isLoading={uploadMutation.isPending}>
            {selectedFiles.length > 0
              ? `Upload ${selectedFiles.length} file${selectedFiles.length === 1 ? '' : 's'}`
              : 'Upload'}
          </Button>
        </div>
      </div>
    </div>,
  )
}
