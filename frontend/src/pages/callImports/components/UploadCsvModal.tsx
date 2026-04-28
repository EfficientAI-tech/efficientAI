import { useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { AlertCircle, FileText, Upload, X } from 'lucide-react'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'

interface UploadCsvModalProps {
  open: boolean
  onClose: () => void
}

const REQUIRED_HEADERS = ['callid', 'transcript']
const MAX_BYTES = 10 * 1024 * 1024

function renderModal(content: ReactNode) {
  if (typeof document === 'undefined') return null
  return createPortal(content, document.body)
}

async function preflight(file: File): Promise<string | null> {
  if (!file.name.toLowerCase().endsWith('.csv')) {
    return 'File must be a .csv'
  }
  if (file.size > MAX_BYTES) {
    return 'CSV exceeds 10 MB; please split the file.'
  }
  try {
    const head = await file.slice(0, 4096).text()
    const firstLine = head.split(/\r?\n/, 1)[0] ?? ''
    if (!firstLine.trim()) {
      return 'CSV is missing a header row.'
    }
    const headers = firstLine
      .split(',')
      .map((h) => h.replace(/^\ufeff/, '').trim().toLowerCase().replace(/^"|"$/g, ''))
    const missing = REQUIRED_HEADERS.filter((h) => !headers.includes(h))
    if (missing.length > 0) {
      return `CSV is missing required headers: ${missing.join(', ')}. Required (case-insensitive): CallID, Transcript. Optional: Recording URL.`
    }
  } catch {
    // Don't block on read errors; the server will validate.
  }
  return null
}

export default function UploadCsvModal({ open, onClose }: UploadCsvModalProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [clientError, setClientError] = useState<string | null>(null)

  const uploadMutation = useMutation({
    mutationFn: (f: File) => apiClient.uploadCallImport(f),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      handleClose()
      navigate(`/call-imports/${data.id}`)
    },
  })

  const handleClose = () => {
    setFile(null)
    setClientError(null)
    uploadMutation.reset()
    onClose()
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const next = e.target.files?.[0] ?? null
    setFile(next)
    setClientError(null)
    uploadMutation.reset()
    if (next) {
      const err = await preflight(next)
      if (err) setClientError(err)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return
    const err = await preflight(file)
    if (err) {
      setClientError(err)
      return
    }
    setClientError(null)
    uploadMutation.mutate(file)
  }

  if (!open) return null

  const serverError = (() => {
    if (!uploadMutation.isError) return null
    const err = uploadMutation.error as any
    const status = err?.response?.status
    const detail: string | undefined = err?.response?.data?.detail
    if (status === 413) {
      return { message: 'CSV exceeds 10 MB; please split the file.', kind: 'size' as const }
    }
    if (detail && /no active exotel/i.test(detail)) {
      return { message: detail, kind: 'integration' as const }
    }
    return { message: detail || err?.message || 'Upload failed', kind: 'generic' as const }
  })()

  return renderModal(
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999]">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Upload className="h-5 w-5 text-primary-600" />
            Upload Call Import CSV
          </h3>
          <button
            onClick={handleClose}
            disabled={uploadMutation.isPending}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label htmlFor="csv-file" className="block text-sm font-medium text-gray-700 mb-1">
              CSV File <span className="text-red-500">*</span>
            </label>
            <input
              id="csv-file"
              type="file"
              required
              accept=".csv,text/csv"
              onChange={handleFileChange}
              disabled={uploadMutation.isPending}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:opacity-60"
            />
            {file && (
              <p className="mt-2 text-sm text-gray-600 flex items-center gap-2">
                <FileText className="h-4 w-4 text-gray-400" />
                {file.name} ({(file.size / 1024).toFixed(1)} KB)
              </p>
            )}
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-1">
            <p>
              Required headers (case-insensitive):{' '}
              <code className="bg-blue-100 px-1 rounded">CallID</code>,{' '}
              <code className="bg-blue-100 px-1 rounded">Transcript</code>.
            </p>
            <p>
              Optional: <code className="bg-blue-100 px-1 rounded">Recording URL</code>{' '}
              &mdash; if omitted, we'll resolve it from Exotel using the CallID.
            </p>
            <p>Max file size: 10 MB. Recordings are fetched from Exotel asynchronously.</p>
          </div>

          {clientError && (
            <div className="rounded-md bg-red-50 border border-red-200 p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-red-800">{clientError}</p>
              </div>
            </div>
          )}

          {serverError && (
            <div className="rounded-md bg-red-50 border border-red-200 p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                <div className="text-sm text-red-800 space-y-2">
                  <p>{serverError.message}</p>
                  {serverError.kind === 'integration' && (
                    <Link
                      to="/integrations"
                      onClick={handleClose}
                      className="inline-block font-medium text-red-700 underline hover:text-red-900"
                    >
                      Configure Exotel in Integrations &rarr;
                    </Link>
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              disabled={uploadMutation.isPending}
              className="flex-1"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              isLoading={uploadMutation.isPending}
              disabled={!file || !!clientError || uploadMutation.isPending}
              className="flex-1"
            >
              Upload
            </Button>
          </div>
        </form>
      </div>
    </div>,
  )
}
