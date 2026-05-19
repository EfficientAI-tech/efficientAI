import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileSpreadsheet,
  FileText,
  Upload,
  UploadCloud,
  X,
} from 'lucide-react'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import type {
  CallImportPreviewResponse,
  CallImportPreviewSheet,
  CallImportTag,
  CallImportUploadResponse,
} from '../../../types/api'

interface UploadCsvModalProps {
  open: boolean
  onClose: () => void
}

const MAX_BYTES = 10 * 1024 * 1024
const STEP_COUNT = 3

const ALLOWED_EXTENSIONS = ['.csv', '.xlsx', '.xlsm'] as const
const ACCEPT_ATTR =
  '.csv,text/csv,.xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

// All possible mapping targets for a source column. The first three are
// the system fields the backend understands natively; "preserve" rides
// through untouched under the original header; "custom" renames into a
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

interface UploadProgress {
  total: number
  completed: number
  current: string | null
  failures: { sheet: string; error: string }[]
}

const SYSTEM_FIELD_NAMES = new Set(['external_call_id', 'transcript', 'recording_url'])

function renderModal(content: ReactNode) {
  if (typeof document === 'undefined') return null
  return createPortal(content, document.body)
}

function getExtension(filename: string): string {
  const idx = filename.lastIndexOf('.')
  return idx >= 0 ? filename.slice(idx).toLowerCase() : ''
}

async function preflight(file: File): Promise<string | null> {
  const ext = getExtension(file.name)
  if (!ALLOWED_EXTENSIONS.includes(ext as (typeof ALLOWED_EXTENSIONS)[number])) {
    return `File must be one of: ${ALLOWED_EXTENSIONS.join(', ')}`
  }
  if (file.size > MAX_BYTES) {
    return 'File exceeds 10 MB; please split it.'
  }
  return null
}

// Heuristic suggestion for a single source header. Match common naming
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
  // source column can map to each system field.
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

interface SheetValidation {
  externalCallIdCount: number
  transcriptCount: number
  recordingUrlCount: number
  customNamesIncomplete: boolean
  customNamesUnique: boolean
  customNamesCollideWithSystem: boolean
  isValid: boolean
}

function validateColumnRows(columnRows: ColumnRow[]): SheetValidation {
  const externalCallIdCount = columnRows.filter(
    (r) => r.type === 'external_call_id',
  ).length
  const transcriptCount = columnRows.filter((r) => r.type === 'transcript').length
  const recordingUrlCount = columnRows.filter((r) => r.type === 'recording_url').length

  const customRows = columnRows.filter((r) => r.type === 'custom')
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

  const isValid =
    externalCallIdCount === 1 &&
    transcriptCount <= 1 &&
    recordingUrlCount <= 1 &&
    !customNamesIncomplete &&
    customNamesUnique &&
    !customNamesCollideWithSystem

  return {
    externalCallIdCount,
    transcriptCount,
    recordingUrlCount,
    customNamesIncomplete,
    customNamesUnique,
    customNamesCollideWithSystem,
    isValid,
  }
}

interface SheetMappingUIProps {
  sheet: CallImportPreviewSheet
  columnRows: ColumnRow[]
  onChange: (next: ColumnRow[]) => void
  disabled: boolean
}

function SheetMappingTable({
  sheet,
  columnRows,
  onChange,
  disabled,
}: SheetMappingUIProps) {
  const validation = validateColumnRows(columnRows)
  const customRows = columnRows.filter((r) => r.type === 'custom')

  const updateColumnRow = (idx: number, patch: Partial<ColumnRow>) => {
    const next = columnRows.map((row, i) => (i === idx ? { ...row, ...patch } : row))
    if (
      patch.type &&
      (patch.type === 'external_call_id' ||
        patch.type === 'transcript' ||
        patch.type === 'recording_url')
    ) {
      for (let i = 0; i < next.length; i += 1) {
        if (i !== idx && next[i].type === patch.type) {
          next[i] = { ...next[i], type: 'skip' }
        }
      }
    }
    onChange(next)
  }

  return (
    <div>
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <div className="grid grid-cols-2 bg-gray-50 px-3 py-2 text-xs font-medium text-gray-600 border-b border-gray-200">
          <div>Source column</div>
          <div>Map to / Store as</div>
        </div>
        <div className="max-h-[480px] overflow-y-auto divide-y divide-gray-100">
          {columnRows.length === 0 ? (
            <p className="px-3 py-3 text-xs text-gray-500">
              No columns detected on sheet "{sheet.name}". Pick a different sheet
              or fix the source file.
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
              const customMissing = row.type === 'custom' && !row.customName.trim()
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
                      disabled={disabled}
                      className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-primary-500 disabled:opacity-60"
                    >
                      <option value="skip">— Skip (don't import) —</option>
                      <option value="external_call_id">External Call ID *</option>
                      <option value="transcript">Transcript</option>
                      <option value="recording_url">Recording URL</option>
                      <option value="preserve">Keep as "{row.csvHeader}"</option>
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
                        disabled={disabled}
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
        {validation.externalCallIdCount === 0 && (
          <p className="text-xs text-red-600">
            One column must be mapped to <strong>External Call ID</strong>.
          </p>
        )}
        {validation.externalCallIdCount > 1 && (
          <p className="text-xs text-red-600">
            Only one column can be mapped to <strong>External Call ID</strong>.
          </p>
        )}
        {validation.transcriptCount > 1 && (
          <p className="text-xs text-red-600">
            Only one column can be mapped to <strong>Transcript</strong>.
          </p>
        )}
        {validation.recordingUrlCount > 1 && (
          <p className="text-xs text-red-600">
            Only one column can be mapped to <strong>Recording URL</strong>.
          </p>
        )}
        {validation.customNamesIncomplete && (
          <p className="text-xs text-red-600">
            Every custom-named column needs a destination field name.
          </p>
        )}
        {!validation.customNamesUnique && (
          <p className="text-xs text-red-600">Custom field names must be unique.</p>
        )}
        {validation.customNamesCollideWithSystem && (
          <p className="text-xs text-red-600">
            Custom names cannot be{' '}
            <code className="bg-red-50 px-1 rounded">external_call_id</code>,{' '}
            <code className="bg-red-50 px-1 rounded">transcript</code>, or{' '}
            <code className="bg-red-50 px-1 rounded">recording_url</code>.
          </p>
        )}
      </div>
    </div>
  )
}

export default function UploadCsvModal({ open, onClose }: UploadCsvModalProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const [step, setStep] = useState(1)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<CallImportPreviewResponse | null>(null)
  // Per-sheet column mapping state, keyed by sheet name. Built lazily as
  // sheets get selected so unselected sheets aren't paying validation tax.
  const [sheetMappings, setSheetMappings] = useState<Record<string, ColumnRow[]>>({})
  const [selectedSheetNames, setSelectedSheetNames] = useState<string[]>([])
  const [expandedSheet, setExpandedSheet] = useState<string | null>(null)
  const [clientError, setClientError] = useState<string | null>(null)
  const [selectedProvider, setSelectedProvider] = useState('')
  const [selectedIntegrationId, setSelectedIntegrationId] = useState('')
  const [dataset, setDataset] = useState('')
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadIntegrationHint, setUploadIntegrationHint] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { data: telephonyConfigs = [] } = useQuery({
    queryKey: ['telephony-configs', open],
    queryFn: () => apiClient.listTelephonyConfigs(),
    enabled: open,
  })

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

  const previewMutation = useMutation({
    mutationFn: (f: File) => apiClient.previewCallImportFile(f),
    onSuccess: (data) => {
      setPreview(data)
      // Default selection: just the FIRST usable sheet. Makes the common
      // "I only want one sheet" case a single-click while still letting
      // the user tick additional sheets to fan out into multiple Call
      // Imports. Sheets without headers can't be mapped meaningfully so
      // they stay deselected (and disabled in the picker).
      const usable = data.sheets.filter((s) => s.headers.length > 0).map((s) => s.name)
      setSelectedSheetNames(usable.slice(0, 1))
      const initial: Record<string, ColumnRow[]> = {}
      for (const sheet of data.sheets) {
        if (sheet.headers.length > 0) {
          initial[sheet.name] = buildInitialColumnRows(sheet.headers)
        } else {
          initial[sheet.name] = []
        }
      }
      setSheetMappings(initial)
      setExpandedSheet(usable[0] ?? null)
    },
    onError: () => {
      setPreview(null)
      setSelectedSheetNames([])
      setSheetMappings({})
      setExpandedSheet(null)
    },
  })

  const isUploading = uploadProgress !== null && uploadProgress.completed < uploadProgress.total

  const isXlsx = preview?.format === 'xlsx'
  const sheets = preview?.sheets ?? []
  const usableSheets = useMemo(() => sheets.filter((s) => s.headers.length > 0), [sheets])
  const showSheetPicker = isXlsx && sheets.length > 1

  // Per-sheet validation summary used to gate the Upload button.
  const sheetValidations = useMemo(() => {
    const out: Record<string, SheetValidation> = {}
    for (const name of selectedSheetNames) {
      const cols = sheetMappings[name] ?? []
      out[name] = validateColumnRows(cols)
    }
    return out
  }, [selectedSheetNames, sheetMappings])

  const allSheetsValid =
    selectedSheetNames.length > 0 &&
    selectedSheetNames.every((name) => sheetValidations[name]?.isValid)

  const datasetIsValid = dataset.trim().length > 0

  const canUpload = Boolean(
    file &&
      selectedProvider &&
      selectedIntegrationId &&
      allSheetsValid &&
      datasetIsValid,
  )

  const handleClose = () => {
    setStep(1)
    setFile(null)
    setPreview(null)
    setSheetMappings({})
    setSelectedSheetNames([])
    setExpandedSheet(null)
    setClientError(null)
    setSelectedProvider('')
    setSelectedIntegrationId('')
    setDataset('')
    setSelectedTagIds([])
    setIsDragging(false)
    setUploadProgress(null)
    setUploadError(null)
    setUploadIntegrationHint(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
    previewMutation.reset()
    onClose()
  }

  // Shared file-acceptance pipeline used by the native <input> change
  // event, the drag-and-drop handler, and the explicit "Replace" button.
  // Keeps preflight + sheet/header detection logic in exactly one place.
  const processFile = async (next: File | null) => {
    setFile(next)
    setClientError(null)
    setUploadError(null)
    setUploadProgress(null)
    if (!next) {
      previewMutation.reset()
      setPreview(null)
      setSelectedSheetNames([])
      setSheetMappings({})
      setExpandedSheet(null)
      return
    }
    const err = await preflight(next)
    if (err) {
      setClientError(err)
      previewMutation.reset()
      setPreview(null)
      setSelectedSheetNames([])
      setSheetMappings({})
      setExpandedSheet(null)
      return
    }
    previewMutation.mutate(next)
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const next = e.target.files?.[0] ?? null
    void processFile(next)
  }

  const handleDropZoneClick = () => {
    if (isUploading) return
    fileInputRef.current?.click()
  }

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    if (isUploading) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
    if (!isDragging) setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    if (isUploading) return
    const dropped = e.dataTransfer.files?.[0]
    if (dropped) void processFile(dropped)
  }

  const handleRemoveFile = () => {
    if (isUploading) return
    if (fileInputRef.current) fileInputRef.current.value = ''
    void processFile(null)
  }

  const setSheetMapping = (sheet: string, next: ColumnRow[]) => {
    setSheetMappings((prev) => ({ ...prev, [sheet]: next }))
  }

  const toggleSheetSelected = (name: string) => {
    setSelectedSheetNames((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    )
  }

  const selectAllSheets = () => {
    setSelectedSheetNames(usableSheets.map((s) => s.name))
  }

  const deselectAllSheets = () => {
    setSelectedSheetNames([])
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (step !== STEP_COUNT) return
    if (!file || !preview) return
    if (!canUpload) return

    const err = await preflight(file)
    if (err) {
      setClientError(err)
      return
    }
    setClientError(null)
    setUploadError(null)
    setUploadIntegrationHint(false)

    const targets = selectedSheetNames
    const total = targets.length
    setUploadProgress({ total, completed: 0, current: targets[0] ?? null, failures: [] })

    const created: CallImportUploadResponse[] = []
    for (let i = 0; i < targets.length; i += 1) {
      const sheetName = targets[i]
      setUploadProgress({
        total,
        completed: i,
        current: sheetName,
        failures: [],
      })
      const cols = sheetMappings[sheetName] ?? []
      const externalCallIdRow = cols.find((r) => r.type === 'external_call_id')
      const transcriptRow = cols.find((r) => r.type === 'transcript')
      const recordingRow = cols.find((r) => r.type === 'recording_url')
      const extraColumns = cols
        .filter((r) => r.type === 'preserve')
        .map((r) => r.csvHeader)
      const customColumnMapping = (() => {
        const out: Record<string, string> = {}
        for (const row of cols.filter((r) => r.type === 'custom')) {
          const name = row.customName.trim()
          if (name) out[name] = row.csvHeader
        }
        return out
      })()
      try {
        const resp = await apiClient.uploadCallImport(file, {
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
          sheetName: preview.format === 'xlsx' ? sheetName : null,
        })
        created.push(resp)
      } catch (err) {
        const anyErr = err as {
          response?: { status?: number; data?: { detail?: string } }
          message?: string
        }
        const status = anyErr?.response?.status
        const detail = anyErr?.response?.data?.detail
        let message: string
        if (status === 413) {
          message = 'File exceeds 10 MB; please split it.'
        } else if (detail && /credential|integration/i.test(detail)) {
          message = detail
          setUploadIntegrationHint(true)
        } else {
          message = detail || anyErr?.message || 'Upload failed'
        }
        setUploadError(
          total > 1 ? `Sheet "${sheetName}" failed: ${message}` : message,
        )
        setUploadProgress({
          total,
          completed: i,
          current: null,
          failures: [{ sheet: sheetName, error: message }],
        })
        return
      }
    }

    setUploadProgress({
      total,
      completed: total,
      current: null,
      failures: [],
    })

    queryClient.invalidateQueries({ queryKey: ['call-imports'] })
    queryClient.invalidateQueries({ queryKey: ['call-import-datasets'] })
    handleClose()
    if (created.length > 0) {
      navigate(`/call-imports/${created[0].id}`)
    }
  }

  const providers = useMemo(() => {
    return Array.from(new Set(telephonyConfigs.map((cfg) => cfg.provider).filter(Boolean)))
  }, [telephonyConfigs])

  const integrationOptions = useMemo(() => {
    return telephonyConfigs.filter((cfg) => cfg.provider === selectedProvider)
  }, [telephonyConfigs, selectedProvider])

  // Whenever selection changes, ensure the expanded sheet is one that is
  // actually selected (avoids confusing UI state where an accordion is
  // open for a sheet that the user just unchecked).
  useEffect(() => {
    if (expandedSheet && !selectedSheetNames.includes(expandedSheet)) {
      setExpandedSheet(selectedSheetNames[0] ?? null)
    } else if (!expandedSheet && selectedSheetNames.length > 0) {
      setExpandedSheet(selectedSheetNames[0])
    }
  }, [selectedSheetNames, expandedSheet])

  if (!open) return null

  const previewError = (() => {
    if (!previewMutation.isError) return null
    const err = previewMutation.error as {
      response?: { status?: number; data?: { detail?: string } }
      message?: string
    }
    const detail = err?.response?.data?.detail
    return detail || err?.message || 'Could not read file.'
  })()

  const canNextStep1 = Boolean(selectedProvider && selectedIntegrationId)
  const canNextStep2 = Boolean(
    file &&
      preview &&
      !previewMutation.isPending &&
      !clientError &&
      !previewError &&
      selectedSheetNames.length > 0,
  )

  return renderModal(
    <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
      {/* Step 3 (column mapping) renders a table that can have many rows
          and a "Map to / Store as" column wide enough to hold the select
          + custom-name input — so the modal expands considerably on that
          step. Steps 1 and 2 stay focused since they're just a couple of
          dropdowns / a file picker. */}
      <div
        className={`bg-white rounded-lg shadow-xl w-full mx-4 max-h-[92vh] overflow-y-auto transition-[max-width] duration-200 ${
          step === 3 ? 'max-w-5xl' : 'max-w-2xl'
        }`}
      >
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Upload className="h-5 w-5 text-primary-600" />
            Upload Call Import file
          </h3>
          <button
            onClick={handleClose}
            disabled={isUploading}
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
                  disabled={isUploading}
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
                  disabled={!selectedProvider || isUploading}
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
                  CSV / Excel File <span className="text-red-500">*</span>
                </label>
                {/* Hidden native input — driven by the dropzone below so we
                    can render a modern drag-and-drop UI while still using
                    the browser file picker on click. */}
                <input
                  ref={fileInputRef}
                  id="csv-file"
                  type="file"
                  accept={ACCEPT_ATTR}
                  onChange={handleFileChange}
                  disabled={isUploading}
                  className="sr-only"
                />

                {!file ? (
                  <div
                    role="button"
                    tabIndex={0}
                    aria-label="Choose a CSV or Excel file or drag and drop one here"
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
                      isUploading
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
                      CSV or Excel (.xlsx, .xlsm) · up to 10 MB
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
                        {preview && (
                          <span className="text-gray-400">
                            · {preview.format === 'xlsx' ? 'Excel' : 'CSV'},{' '}
                            {sheets.length} sheet{sheets.length === 1 ? '' : 's'}
                          </span>
                        )}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <button
                        type="button"
                        onClick={handleDropZoneClick}
                        disabled={isUploading}
                        className="text-xs font-medium text-primary-600 hover:text-primary-700 px-2 py-1 rounded hover:bg-primary-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        Replace
                      </button>
                      <button
                        type="button"
                        onClick={handleRemoveFile}
                        disabled={isUploading}
                        aria-label="Remove file"
                        className="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {previewMutation.isPending && (
                <div className="rounded-md bg-gray-50 border border-gray-200 p-3 text-xs text-gray-600">
                  Reading file…
                </div>
              )}

              {previewError && (
                <div className="rounded-md bg-red-50 border border-red-200 p-3">
                  <div className="flex items-start gap-2">
                    <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                    <p className="text-sm text-red-800">{previewError}</p>
                  </div>
                </div>
              )}

              {showSheetPicker && (
                <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-medium text-gray-700">
                      Sheets to import{' '}
                      <span className="text-gray-500 font-normal">
                        ({selectedSheetNames.length} of {usableSheets.length} selected)
                      </span>
                    </p>
                    <div className="flex gap-2 text-xs">
                      <button
                        type="button"
                        onClick={selectAllSheets}
                        className="text-primary-600 hover:text-primary-700 font-medium"
                      >
                        Select all
                      </button>
                      <span className="text-gray-300">·</span>
                      <button
                        type="button"
                        onClick={deselectAllSheets}
                        className="text-gray-600 hover:text-gray-800 font-medium"
                      >
                        Deselect all
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-gray-500">
                    The first sheet is selected by default. Tick additional
                    sheets to import them too — each selected sheet becomes
                    its own Call Import, and you'll map columns separately
                    for each on the next step.
                  </p>
                  <div className="space-y-1">
                    {sheets.map((sheet) => {
                      const checked = selectedSheetNames.includes(sheet.name)
                      const disabled = sheet.headers.length === 0
                      return (
                        <label
                          key={sheet.name}
                          className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer ${
                            disabled
                              ? 'opacity-60 cursor-not-allowed'
                              : 'hover:bg-white'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={disabled}
                            onChange={() => toggleSheetSelected(sheet.name)}
                            className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50"
                          />
                          <span className="text-sm text-gray-800 truncate">
                            {sheet.name}
                          </span>
                          <span className="text-xs text-gray-500 ml-auto">
                            {disabled
                              ? 'no headers'
                              : `${sheet.headers.length} cols · ~${sheet.row_count} rows`}
                          </span>
                        </label>
                      )
                    })}
                  </div>
                </div>
              )}

              {!showSheetPicker && preview && usableSheets.length > 0 && (
                <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">
                  <p className="text-xs font-medium text-gray-600 mb-1">
                    Detected columns
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {usableSheets[0].headers.map((h) => (
                      <span
                        key={h}
                        className="px-2 py-0.5 rounded bg-white border text-xs text-gray-700"
                      >
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
                  For each source column on the left, choose what to import it as
                  on the right.{' '}
                  {selectedSheetNames.length > 1 &&
                    'You\u2019re mapping multiple sheets — each sheet becomes its own Call Import.'}
                </p>

                {selectedSheetNames.length === 1 ? (
                  // Single sheet: render the mapping table directly without
                  // an accordion wrapper to match the pre-multi-sheet UX.
                  <SheetMappingTable
                    sheet={
                      sheets.find((s) => s.name === selectedSheetNames[0]) ?? {
                        name: selectedSheetNames[0],
                        headers: [],
                        row_count: 0,
                      }
                    }
                    columnRows={sheetMappings[selectedSheetNames[0]] ?? []}
                    onChange={(next) => setSheetMapping(selectedSheetNames[0], next)}
                    disabled={isUploading}
                  />
                ) : (
                  <div className="space-y-2">
                    {selectedSheetNames.map((name) => {
                      const sheet = sheets.find((s) => s.name === name)
                      if (!sheet) return null
                      const validation = sheetValidations[name]
                      const isOpen = expandedSheet === name
                      return (
                        <div
                          key={name}
                          className="border border-gray-200 rounded-lg overflow-hidden"
                        >
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedSheet(isOpen ? null : name)
                            }
                            className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 text-left"
                          >
                            {isOpen ? (
                              <ChevronDown className="h-4 w-4 text-gray-500 flex-shrink-0" />
                            ) : (
                              <ChevronRight className="h-4 w-4 text-gray-500 flex-shrink-0" />
                            )}
                            <span className="text-sm font-medium text-gray-800 truncate">
                              {name}
                            </span>
                            <span className="text-xs text-gray-500">
                              · {sheet.headers.length} cols · ~{sheet.row_count} rows
                            </span>
                            {validation?.isValid ? (
                              <CheckCircle2 className="h-4 w-4 text-emerald-500 ml-auto flex-shrink-0" />
                            ) : (
                              <AlertCircle className="h-4 w-4 text-amber-500 ml-auto flex-shrink-0" />
                            )}
                          </button>
                          {isOpen && (
                            <div className="px-3 py-3 border-t border-gray-200">
                              <SheetMappingTable
                                sheet={sheet}
                                columnRows={sheetMappings[name] ?? []}
                                onChange={(next) => setSheetMapping(name, next)}
                                disabled={isUploading}
                              />
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
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
                  disabled={isUploading}
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
                {selectedSheetNames.length > 1 && (
                  <p className="mt-1 text-xs text-gray-500">
                    Shared across all {selectedSheetNames.length} sheets in this upload.
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
                          disabled={isUploading}
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
              Pick a provider + telephony credential first, then for each source
              column choose:
              <code className="bg-blue-100 px-1 rounded ml-1">External Call ID</code>,
              <code className="bg-blue-100 px-1 rounded ml-1">Transcript</code>,
              <code className="bg-blue-100 px-1 rounded ml-1">Recording URL</code>,
              <span className="ml-1">Keep as-is, Custom name, or Skip.</span>
            </p>
            <p>
              <strong>Excel workbooks</strong> with multiple sheets create one
              Call Import per selected sheet. Each sheet has its own column
              mapping but shares the dataset and tags.
            </p>
            <p>
              <strong>Custom name</strong> renames the source column to your own
              field name (e.g. <code className="bg-blue-100 px-1 rounded">agent_name</code>)
              so it flows through the evaluation export under that name.
            </p>
            <p>Max file size: 10 MB. Recordings are fetched asynchronously from the selected provider integration.</p>
          </div>

          {uploadProgress && uploadProgress.total > 1 && (
            <div className="rounded-md bg-blue-50 border border-blue-200 p-3 text-sm text-blue-800">
              Uploaded {uploadProgress.completed} / {uploadProgress.total} sheets
              {uploadProgress.current ? ` (current: "${uploadProgress.current}")` : ''}…
            </div>
          )}

          {clientError && (
            <div className="rounded-md bg-red-50 border border-red-200 p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-red-800">{clientError}</p>
              </div>
            </div>
          )}

          {uploadError && (
            <div className="rounded-md bg-red-50 border border-red-200 p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                <div className="text-sm text-red-800 space-y-2">
                  <p>{uploadError}</p>
                  {uploadIntegrationHint && (
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
              disabled={isUploading}
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
                  isUploading ||
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
                isLoading={isUploading}
                disabled={!canUpload || !!clientError || isUploading}
                className="flex-1"
              >
                {selectedSheetNames.length > 1
                  ? `Upload ${selectedSheetNames.length} sheets`
                  : 'Upload'}
              </Button>
            )}
          </div>
        </form>
      </div>
    </div>,
  )
}
