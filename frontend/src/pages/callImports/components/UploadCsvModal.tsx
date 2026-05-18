import { useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  CheckCircle2,
  FileSpreadsheet,
  FileText,
  Upload,
  UploadCloud,
  X,
} from 'lucide-react'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'
import type { CallImportTag } from '../../../types/api'

interface UploadCsvModalProps {
  open: boolean
  onClose: () => void
}

const MAX_BYTES = 10 * 1024 * 1024
const STEP_COUNT = 3

// All possible mapping targets for a CSV column. The first three are the
// system fields the backend understands natively; "preserve" rides through
// untouched under the original CSV header; "custom" renames into a
// caller-defined field; "skip" drops the column entirely.
type MappingType =
  | 'skip'
  | 'external_call_id'
  | 'transcript'
  | 'recording_url'
  | 'preserve'
  | 'custom'

interface ColumnRow {
  csvHeader: string
  type: MappingType
  customName: string
}

const SYSTEM_FIELD_NAMES = new Set(['external_call_id', 'transcript', 'recording_url'])

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
    if (firstLine.split(',').length < 1) return 'CSV header row is invalid.'
  } catch {
    // Don't block on read errors; the server will validate.
  }
  return null
}

async function readCsvHeaders(file: File): Promise<string[]> {
  const text = await file.slice(0, 65536).text()
  const firstLine = text.split(/\r?\n/, 1)[0] ?? ''
  return firstLine
    .split(',')
    .map((h) => h.replace(/^\ufeff/, '').trim().replace(/^"|"$/g, ''))
    .filter(Boolean)
}

// Heuristic suggestion for a single CSV header. Match common naming
// conventions so the user usually only has to confirm the table rather
// than manually picking each row.
function suggestMapping(header: string): MappingType {
  const norm = header.toLowerCase().trim().replace(/[\s_\-.]+/g, '')
  if (
    norm === 'externalcallid' ||
    norm === 'callid' ||
    norm === 'callsid' ||
    norm === 'sid' ||
    norm === 'calluuid' ||
    norm === 'uuid'
  ) {
    return 'external_call_id'
  }
  if (norm.includes('transcript') || norm.includes('transcription')) {
    return 'transcript'
  }
  if (
    norm.includes('recordingurl') ||
    norm.includes('recordinglink') ||
    norm === 'recording'
  ) {
    return 'recording_url'
  }
  return 'skip'
}

function buildInitialColumnRows(headers: string[]): ColumnRow[] {
  const rows: ColumnRow[] = headers.map((h) => ({
    csvHeader: h,
    type: suggestMapping(h),
    customName: '',
  }))

  // Force exactly one external_call_id (first heuristic match wins; if no
  // header looked like an ID at all, fall back to the first header so the
  // user has a sensible starting point).
  const externalIndices: number[] = []
  rows.forEach((r, i) => {
    if (r.type === 'external_call_id') externalIndices.push(i)
  })
  if (externalIndices.length === 0 && rows.length > 0) {
    rows[0] = { ...rows[0], type: 'external_call_id' }
  } else if (externalIndices.length > 1) {
    for (let i = 1; i < externalIndices.length; i += 1) {
      const idx = externalIndices[i]
      rows[idx] = { ...rows[idx], type: 'skip' }
    }
  }

  // Demote duplicate transcript / recording_url hits to skip — at most one
  // CSV column can map to each system field.
  const dedupe = (target: MappingType) => {
    const found: number[] = []
    rows.forEach((r, i) => {
      if (r.type === target) found.push(i)
    })
    for (let i = 1; i < found.length; i += 1) {
      rows[found[i]] = { ...rows[found[i]], type: 'skip' }
    }
  }
  dedupe('transcript')
  dedupe('recording_url')

  return rows
}

export default function UploadCsvModal({ open, onClose }: UploadCsvModalProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [clientError, setClientError] = useState<string | null>(null)
  const [selectedProvider, setSelectedProvider] = useState('')
  const [selectedIntegrationId, setSelectedIntegrationId] = useState('')
  const [columnRows, setColumnRows] = useState<ColumnRow[]>([])
  const [dataset, setDataset] = useState('')
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { data: telephonyConfigs = [] } = useQuery({
    queryKey: ['telephony-configs', open],
    queryFn: () => apiClient.listTelephonyConfigs(),
    enabled: open,
  })

  const { data: existingDatasets = [] } = useQuery({
    queryKey: ['call-import-datasets'],
    queryFn: () => apiClient.listCallImportDatasets(),
    enabled: open,
  })

  const { data: allTags = [] } = useQuery({
    queryKey: ['call-import-tags'],
    queryFn: () => apiClient.listCallImportTags(),
    enabled: open,
  })

  // Derived counts / payload from the unified columnRows model.
  const externalCallIdRow = useMemo(
    () => columnRows.find((r) => r.type === 'external_call_id'),
    [columnRows],
  )
  const transcriptRow = useMemo(
    () => columnRows.find((r) => r.type === 'transcript'),
    [columnRows],
  )
  const recordingRow = useMemo(
    () => columnRows.find((r) => r.type === 'recording_url'),
    [columnRows],
  )
  const externalCallIdCount = useMemo(
    () => columnRows.filter((r) => r.type === 'external_call_id').length,
    [columnRows],
  )
  const transcriptCount = useMemo(
    () => columnRows.filter((r) => r.type === 'transcript').length,
    [columnRows],
  )
  const recordingUrlCount = useMemo(
    () => columnRows.filter((r) => r.type === 'recording_url').length,
    [columnRows],
  )

  const customRows = useMemo(
    () => columnRows.filter((r) => r.type === 'custom'),
    [columnRows],
  )
  const customNamesIncomplete = customRows.some((r) => !r.customName.trim())
  const customNamesUnique = (() => {
    const seen = new Set<string>()
    for (const row of customRows) {
      const name = row.customName.trim().toLowerCase()
      if (!name) continue
      if (seen.has(name)) return false
      seen.add(name)
    }
    return true
  })()
  const customNamesCollideWithSystem = customRows.some((r) =>
    SYSTEM_FIELD_NAMES.has(r.customName.trim().toLowerCase()),
  )

  const customColumnMapping = useMemo(() => {
    const out: Record<string, string> = {}
    for (const row of customRows) {
      const name = row.customName.trim()
      if (name) out[name] = row.csvHeader
    }
    return out
  }, [customRows])

  const extraColumns = useMemo(
    () => columnRows.filter((r) => r.type === 'preserve').map((r) => r.csvHeader),
    [columnRows],
  )

  const uploadMutation = useMutation({
    mutationFn: (f: File) =>
      apiClient.uploadCallImport(f, {
        provider: selectedProvider,
        telephonyIntegrationId: selectedIntegrationId,
        columnMapping: {
          external_call_id: externalCallIdRow?.csvHeader || '',
          transcript: transcriptRow?.csvHeader || null,
          recording_url: recordingRow?.csvHeader || null,
        },
        extraColumns,
        customColumnMapping,
        dataset: dataset.trim() ? dataset.trim() : null,
        tagIds: selectedTagIds,
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      queryClient.invalidateQueries({ queryKey: ['call-import-datasets'] })
      handleClose()
      navigate(`/call-imports/${data.id}`)
    },
  })

  const handleClose = () => {
    setStep(1)
    setFile(null)
    setHeaders([])
    setClientError(null)
    setSelectedProvider('')
    setSelectedIntegrationId('')
    setColumnRows([])
    setDataset('')
    setSelectedTagIds([])
    setIsDragging(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
    uploadMutation.reset()
    onClose()
  }

  // Shared file-acceptance pipeline used by the native <input> change event,
  // the drag-and-drop handler, and the explicit "Replace" button. Keeps
  // preflight + header-detection logic in exactly one place.
  const processFile = async (next: File | null) => {
    setFile(next)
    setClientError(null)
    uploadMutation.reset()
    if (!next) {
      setHeaders([])
      setColumnRows([])
      return
    }
    const err = await preflight(next)
    if (err) {
      setClientError(err)
      setHeaders([])
      setColumnRows([])
      return
    }
    try {
      const detected = await readCsvHeaders(next)
      setHeaders(detected)
      setColumnRows(buildInitialColumnRows(detected))
    } catch {
      setClientError('Unable to parse CSV headers.')
      setHeaders([])
      setColumnRows([])
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const next = e.target.files?.[0] ?? null
    void processFile(next)
  }

  const handleDropZoneClick = () => {
    if (uploadMutation.isPending) return
    fileInputRef.current?.click()
  }

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    if (uploadMutation.isPending) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
    if (!isDragging) setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    // Ignore leave events that fire when the cursor moves over a child
    // element; only clear the highlight when leaving the dropzone itself.
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    if (uploadMutation.isPending) return
    const dropped = e.dataTransfer.files?.[0]
    if (dropped) void processFile(dropped)
  }

  const handleRemoveFile = () => {
    if (uploadMutation.isPending) return
    if (fileInputRef.current) fileInputRef.current.value = ''
    void processFile(null)
  }

  const updateColumnRow = (idx: number, patch: Partial<ColumnRow>) => {
    setColumnRows((prev) => {
      const next = prev.map((row, i) => (i === idx ? { ...row, ...patch } : row))
      // System fields are single-valued: switching one row into a system
      // type kicks any other row that previously held that type back to skip.
      if (patch.type && (patch.type === 'external_call_id' || patch.type === 'transcript' || patch.type === 'recording_url')) {
        for (let i = 0; i < next.length; i += 1) {
          if (i !== idx && next[i].type === patch.type) {
            next[i] = { ...next[i], type: 'skip' }
          }
        }
      }
      return next
    })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    // Only the final step's "Upload" button should ever trigger the mutation.
    // Guard here so a stray Enter press or a button-type-swap race during a
    // step transition can't fire the upload before the user has confirmed.
    if (step !== STEP_COUNT) return
    if (!file) return
    const err = await preflight(file)
    if (err) {
      setClientError(err)
      return
    }
    setClientError(null)
    uploadMutation.mutate(file)
  }

  const providers = useMemo(() => {
    return Array.from(new Set(telephonyConfigs.map((cfg) => cfg.provider).filter(Boolean)))
  }, [telephonyConfigs])

  const integrationOptions = useMemo(() => {
    return telephonyConfigs.filter((cfg) => cfg.provider === selectedProvider)
  }, [telephonyConfigs, selectedProvider])

  if (!open) return null

  const serverError = (() => {
    if (!uploadMutation.isError) return null
    const err = uploadMutation.error as any
    const status = err?.response?.status
    const detail: string | undefined = err?.response?.data?.detail
    if (status === 413) {
      return { message: 'CSV exceeds 10 MB; please split the file.', kind: 'size' as const }
    }
    if (detail && /credential|integration/i.test(detail)) {
      return { message: detail, kind: 'integration' as const }
    }
    return { message: detail || err?.message || 'Upload failed', kind: 'generic' as const }
  })()

  const canNextStep1 = Boolean(selectedProvider && selectedIntegrationId)
  const canNextStep2 = Boolean(file && headers.length > 0 && !clientError)
  const datasetIsValid = dataset.trim().length > 0
  const canUpload = Boolean(
    file &&
      selectedProvider &&
      selectedIntegrationId &&
      externalCallIdCount === 1 &&
      transcriptCount <= 1 &&
      recordingUrlCount <= 1 &&
      !customNamesIncomplete &&
      customNamesUnique &&
      !customNamesCollideWithSystem &&
      datasetIsValid,
  )

  return renderModal(
    <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
      <div className="bg-white rounded-lg shadow-xl max-w-xl w-full mx-4 max-h-[90vh] overflow-y-auto">
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
          <div className="flex items-center gap-2 text-xs">
            {Array.from({ length: STEP_COUNT }).map((_, idx) => {
              const current = idx + 1
              const done = step > current
              return (
                <div key={current} className="flex items-center gap-2">
                  <span
                    className={`h-6 w-6 rounded-full flex items-center justify-center font-semibold ${
                      done
                        ? 'bg-green-100 text-green-700'
                        : step === current
                          ? 'bg-primary-100 text-primary-700'
                          : 'bg-gray-100 text-gray-500'
                    }`}
                  >
                    {done ? <CheckCircle2 className="h-3.5 w-3.5" /> : current}
                  </span>
                  {current < STEP_COUNT && <span className="text-gray-300">—</span>}
                </div>
              )
            })}
          </div>

          {step === 1 && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Telephony Provider <span className="text-red-500">*</span>
                </label>
                <select
                  value={selectedProvider}
                  onChange={(e) => {
                    setSelectedProvider(e.target.value)
                    setSelectedIntegrationId('')
                  }}
                  disabled={uploadMutation.isPending}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                >
                  <option value="">Select provider</option>
                  {providers.map((provider) => (
                    <option key={provider} value={provider}>
                      {provider}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Integration Credential <span className="text-red-500">*</span>
                </label>
                <select
                  value={selectedIntegrationId}
                  onChange={(e) => setSelectedIntegrationId(e.target.value)}
                  disabled={!selectedProvider || uploadMutation.isPending}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 disabled:bg-gray-100"
                >
                  <option value="">Select credential</option>
                  {integrationOptions.map((cfg) => (
                    <option key={cfg.id} value={cfg.id}>
                      {cfg.name || `${cfg.provider} (${cfg.id.slice(0, 8)})`}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <div>
                <label htmlFor="csv-file" className="block text-sm font-medium text-gray-700 mb-1">
                  CSV File <span className="text-red-500">*</span>
                </label>
                {/* Hidden native input — driven by the dropzone below so we
                    can render a modern drag-and-drop UI while still using
                    the browser file picker on click. */}
                <input
                  ref={fileInputRef}
                  id="csv-file"
                  type="file"
                  accept=".csv,text/csv"
                  onChange={handleFileChange}
                  disabled={uploadMutation.isPending}
                  className="sr-only"
                />

                {!file ? (
                  <div
                    role="button"
                    tabIndex={0}
                    aria-label="Choose a CSV file or drag and drop one here"
                    onClick={handleDropZoneClick}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        handleDropZoneClick()
                      }
                    }}
                    onDragOver={handleDragOver}
                    onDragEnter={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    className={`group relative w-full rounded-xl border-2 border-dashed transition-colors px-6 py-8 flex flex-col items-center justify-center text-center cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 ${
                      uploadMutation.isPending
                        ? 'opacity-60 cursor-not-allowed border-gray-200 bg-gray-50'
                        : isDragging
                          ? 'border-primary-500 bg-primary-50/60'
                          : 'border-gray-300 bg-gray-50/40 hover:border-primary-400 hover:bg-primary-50/30'
                    }`}
                  >
                    <div
                      className={`h-12 w-12 rounded-full flex items-center justify-center mb-3 transition-colors ${
                        isDragging
                          ? 'bg-primary-100 text-primary-600'
                          : 'bg-white border border-gray-200 text-gray-500 group-hover:text-primary-600 group-hover:border-primary-200'
                      }`}
                    >
                      <UploadCloud className="h-6 w-6" />
                    </div>
                    <p className="text-sm font-medium text-gray-800">
                      <span className="text-primary-600">Click to upload</span>{' '}
                      <span className="text-gray-600">or drag and drop</span>
                    </p>
                    <p className="mt-1 text-xs text-gray-500">
                      CSV file, UTF-8 encoded · up to 10 MB
                    </p>
                  </div>
                ) : (
                  <div className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
                    <div className="h-10 w-10 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center flex-shrink-0">
                      <FileSpreadsheet className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p
                        className="text-sm font-medium text-gray-900 truncate"
                        title={file.name}
                      >
                        {file.name}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-1.5">
                        <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                        {(file.size / 1024).toFixed(1)} KB
                        {headers.length > 0 && (
                          <span className="text-gray-400">
                            · {headers.length} column{headers.length === 1 ? '' : 's'} detected
                          </span>
                        )}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <button
                        type="button"
                        onClick={handleDropZoneClick}
                        disabled={uploadMutation.isPending}
                        className="text-xs font-medium text-primary-600 hover:text-primary-700 px-2 py-1 rounded hover:bg-primary-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        Replace
                      </button>
                      <button
                        type="button"
                        onClick={handleRemoveFile}
                        disabled={uploadMutation.isPending}
                        aria-label="Remove file"
                        className="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                )}
              </div>
              {headers.length > 0 && (
                <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">
                  <p className="text-xs font-medium text-gray-600 mb-1">Detected columns</p>
                  <div className="flex flex-wrap gap-1">
                    {headers.map((h) => (
                      <span key={h} className="px-2 py-0.5 rounded bg-white border text-xs text-gray-700">
                        {h}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <div>
                <p className="text-sm font-medium text-gray-700">
                  Column mapping <span className="text-red-500">*</span>
                </p>
                <p className="text-xs text-gray-500 mt-0.5 mb-2">
                  For each CSV column on the left, choose what to import it as on the right.
                </p>
                <div className="border border-gray-200 rounded-lg overflow-hidden">
                  <div className="grid grid-cols-2 bg-gray-50 px-3 py-2 text-xs font-medium text-gray-600 border-b border-gray-200">
                    <div>CSV column</div>
                    <div>Map to / Store as</div>
                  </div>
                  <div className="max-h-72 overflow-y-auto divide-y divide-gray-100">
                    {columnRows.length === 0 ? (
                      <p className="px-3 py-3 text-xs text-gray-500">
                        No columns detected. Go back and pick a CSV file.
                      </p>
                    ) : (
                      columnRows.map((row, idx) => {
                        const trimmedName = row.customName.trim().toLowerCase()
                        const customDuplicate =
                          row.type === 'custom' &&
                          !!trimmedName &&
                          customRows.filter(
                            (r) => r.customName.trim().toLowerCase() === trimmedName,
                          ).length > 1
                        const customCollidesSystem =
                          row.type === 'custom' && SYSTEM_FIELD_NAMES.has(trimmedName)
                        const customMissing =
                          row.type === 'custom' && !row.customName.trim()
                        return (
                          <div
                            key={`${row.csvHeader}-${idx}`}
                            className="grid grid-cols-2 gap-2 items-start px-3 py-2"
                          >
                            <div
                              className="text-sm text-gray-800 truncate flex items-center gap-1.5 pt-1.5"
                              title={row.csvHeader}
                            >
                              <FileText className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
                              <span className="truncate">{row.csvHeader}</span>
                            </div>
                            <div className="space-y-1">
                              <select
                                value={row.type}
                                onChange={(e) =>
                                  updateColumnRow(idx, {
                                    type: e.target.value as MappingType,
                                  })
                                }
                                disabled={uploadMutation.isPending}
                                className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-primary-500 disabled:opacity-60"
                              >
                                <option value="skip">— Skip (don't import) —</option>
                                <option value="external_call_id">
                                  External Call ID *
                                </option>
                                <option value="transcript">Transcript</option>
                                <option value="recording_url">Recording URL</option>
                                <option value="preserve">
                                  Keep as "{row.csvHeader}"
                                </option>
                                <option value="custom">Custom name…</option>
                              </select>
                              {row.type === 'custom' && (
                                <input
                                  type="text"
                                  value={row.customName}
                                  onChange={(e) =>
                                    updateColumnRow(idx, { customName: e.target.value })
                                  }
                                  placeholder="store as (e.g. agent_name)"
                                  disabled={uploadMutation.isPending}
                                  className={`w-full px-2 py-1.5 border rounded text-sm focus:ring-2 focus:ring-primary-500 disabled:opacity-60 ${
                                    customDuplicate || customCollidesSystem || customMissing
                                      ? 'border-red-300'
                                      : 'border-gray-300'
                                  }`}
                                />
                              )}
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>
                </div>
                <div className="mt-2 space-y-1">
                  {externalCallIdCount === 0 && (
                    <p className="text-xs text-red-600">
                      One column must be mapped to <strong>External Call ID</strong>.
                    </p>
                  )}
                  {externalCallIdCount > 1 && (
                    <p className="text-xs text-red-600">
                      Only one column can be mapped to <strong>External Call ID</strong>.
                    </p>
                  )}
                  {transcriptCount > 1 && (
                    <p className="text-xs text-red-600">
                      Only one column can be mapped to <strong>Transcript</strong>.
                    </p>
                  )}
                  {recordingUrlCount > 1 && (
                    <p className="text-xs text-red-600">
                      Only one column can be mapped to <strong>Recording URL</strong>.
                    </p>
                  )}
                  {customNamesIncomplete && (
                    <p className="text-xs text-red-600">
                      Every custom-named column needs a destination field name.
                    </p>
                  )}
                  {!customNamesUnique && (
                    <p className="text-xs text-red-600">
                      Custom field names must be unique.
                    </p>
                  )}
                  {customNamesCollideWithSystem && (
                    <p className="text-xs text-red-600">
                      Custom names cannot be{' '}
                      <code className="bg-red-50 px-1 rounded">external_call_id</code>,{' '}
                      <code className="bg-red-50 px-1 rounded">transcript</code>, or{' '}
                      <code className="bg-red-50 px-1 rounded">recording_url</code>.
                    </p>
                  )}
                </div>
              </div>

              <div>
                <label htmlFor="csv-dataset" className="block text-sm font-medium text-gray-700 mb-1">
                  Dataset <span className="text-red-500">*</span>
                </label>
                <input
                  id="csv-dataset"
                  type="text"
                  list="csv-dataset-suggestions"
                  value={dataset}
                  onChange={(e) => setDataset(e.target.value)}
                  disabled={uploadMutation.isPending}
                  placeholder="e.g., march-2026-batch"
                  required
                  aria-invalid={!datasetIsValid}
                  className={`w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:opacity-60 ${
                    datasetIsValid ? 'border-gray-300' : 'border-red-300'
                  }`}
                />
                <datalist id="csv-dataset-suggestions">
                  {existingDatasets.map((d) => (
                    <option key={d} value={d} />
                  ))}
                </datalist>
                {!datasetIsValid && (
                  <p className="mt-1 text-xs text-red-600">
                    Dataset is required. Pick an existing one from the suggestions or
                    type a new label (e.g. <code className="bg-red-50 px-1 rounded">march-2026-batch</code>).
                  </p>
                )}
              </div>

              {allTags.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Tags <span className="text-gray-400 font-normal">(optional)</span>
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {allTags.map((tag: CallImportTag) => {
                      const active = selectedTagIds.includes(tag.id)
                      return (
                        <button
                          type="button"
                          key={tag.id}
                          onClick={() =>
                            setSelectedTagIds((prev) =>
                              prev.includes(tag.id)
                                ? prev.filter((id) => id !== tag.id)
                                : [...prev, tag.id],
                            )
                          }
                          disabled={uploadMutation.isPending}
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
                </div>
              )}
            </div>
          )}

          <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-1">
            <p>
              Pick a provider + telephony credential first, then for each CSV column choose:
              <code className="bg-blue-100 px-1 rounded ml-1">External Call ID</code>,
              <code className="bg-blue-100 px-1 rounded ml-1">Transcript</code>,
              <code className="bg-blue-100 px-1 rounded ml-1">Recording URL</code>,
              <span className="ml-1">Keep as-is, Custom name, or Skip.</span>
            </p>
            <p>
              <strong>Custom name</strong> renames the CSV column to your own field name
              (e.g. <code className="bg-blue-100 px-1 rounded">agent_name</code>) so it
              flows through the evaluation export under that name.
            </p>
            <p>Max file size: 10 MB. Recordings are fetched asynchronously from the selected provider integration.</p>
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
                      Configure telephony credentials in Integrations &rarr;
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
              onClick={() => {
                if (step === 1) handleClose()
                else setStep((s) => Math.max(1, s - 1))
              }}
              disabled={uploadMutation.isPending}
              className="flex-1"
            >
              {step === 1 ? 'Cancel' : 'Back'}
            </Button>
            {step < STEP_COUNT ? (
              <Button
                key="next-step"
                type="button"
                variant="primary"
                onClick={() => setStep((s) => Math.min(STEP_COUNT, s + 1))}
                disabled={
                  uploadMutation.isPending ||
                  (step === 1 && !canNextStep1) ||
                  (step === 2 && !canNextStep2)
                }
                className="flex-1"
              >
                Next
              </Button>
            ) : (
              <Button
                key="upload-submit"
                type="submit"
                variant="primary"
                isLoading={uploadMutation.isPending}
                disabled={!canUpload || !!clientError || uploadMutation.isPending}
                className="flex-1"
              >
                Upload
              </Button>
            )}
          </div>
        </form>
      </div>
    </div>,
  )
}
