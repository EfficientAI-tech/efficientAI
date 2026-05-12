import { useMemo, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { AlertCircle, CheckCircle2, FileText, Plus, Trash2, Upload, X } from 'lucide-react'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'
import type { CallImportTag } from '../../../types/api'

interface UploadCsvModalProps {
  open: boolean
  onClose: () => void
}

const MAX_BYTES = 10 * 1024 * 1024
const STEP_COUNT = 3

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

export default function UploadCsvModal({ open, onClose }: UploadCsvModalProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [clientError, setClientError] = useState<string | null>(null)
  const [selectedProvider, setSelectedProvider] = useState('')
  const [selectedIntegrationId, setSelectedIntegrationId] = useState('')
  const [mapExternalCallId, setMapExternalCallId] = useState('')
  const [mapTranscript, setMapTranscript] = useState('')
  const [mapRecordingUrl, setMapRecordingUrl] = useState('')
  const [extraColumns, setExtraColumns] = useState<string[]>([])
  const [customColumns, setCustomColumns] = useState<
    Array<{ id: string; name: string; csvHeader: string }>
  >([])
  const [dataset, setDataset] = useState('')
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([])

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

  const customColumnMapping = useMemo(() => {
    const out: Record<string, string> = {}
    for (const row of customColumns) {
      const name = row.name.trim()
      const header = row.csvHeader.trim()
      if (name && header) out[name] = header
    }
    return out
  }, [customColumns])

  const uploadMutation = useMutation({
    mutationFn: (f: File) =>
      apiClient.uploadCallImport(f, {
        provider: selectedProvider,
        telephonyIntegrationId: selectedIntegrationId,
        columnMapping: {
          external_call_id: mapExternalCallId,
          transcript: mapTranscript || null,
          recording_url: mapRecordingUrl || null,
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
    setMapExternalCallId('')
    setMapTranscript('')
    setMapRecordingUrl('')
    setExtraColumns([])
    setCustomColumns([])
    setDataset('')
    setSelectedTagIds([])
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
      if (err) {
        setClientError(err)
        setHeaders([])
      } else {
        try {
          const detected = await readCsvHeaders(next)
          setHeaders(detected)
          if (!mapExternalCallId && detected.length > 0) {
            setMapExternalCallId(detected[0])
          }
        } catch {
          setClientError('Unable to parse CSV headers.')
          setHeaders([])
        }
      }
    }
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
  const customColumnRowsValid = customColumns.every((row) => {
    const hasName = !!row.name.trim()
    const hasHeader = !!row.csvHeader.trim()
    return (hasName && hasHeader) || (!hasName && !hasHeader)
  })
  const customNamesUnique = (() => {
    const seen = new Set<string>()
    for (const row of customColumns) {
      const name = row.name.trim().toLowerCase()
      if (!name) continue
      if (seen.has(name)) return false
      seen.add(name)
    }
    return true
  })()
  const canUpload = Boolean(
    file &&
      selectedProvider &&
      selectedIntegrationId &&
      mapExternalCallId &&
      customColumnRowsValid &&
      customNamesUnique,
  )

  const toggleExtraColumn = (column: string) => {
    setExtraColumns((prev) =>
      prev.includes(column) ? prev.filter((c) => c !== column) : [...prev, column],
    )
  }

  const addCustomColumn = () => {
    setCustomColumns((prev) => [
      ...prev,
      { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, name: '', csvHeader: '' },
    ])
  }
  const updateCustomColumn = (
    id: string,
    patch: Partial<{ name: string; csvHeader: string }>,
  ) => {
    setCustomColumns((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)))
  }
  const removeCustomColumn = (id: string) => {
    setCustomColumns((prev) => prev.filter((row) => row.id !== id))
  }

  const customMappedHeaders = customColumns.map((row) => row.csvHeader).filter(Boolean)
  const unavailableForExtras = new Set(
    [mapExternalCallId, mapTranscript, mapRecordingUrl, ...customMappedHeaders].filter(Boolean),
  )
  const availableExtraColumns = headers.filter((h) => !unavailableForExtras.has(h))

  return renderModal(
    <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
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
              <div className="grid grid-cols-1 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    External Call ID Column <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={mapExternalCallId}
                    onChange={(e) => setMapExternalCallId(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                  >
                    <option value="">Select column</option>
                    {headers.map((h) => (
                      <option key={h} value={h}>{h}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Transcript Column</label>
                  <select
                    value={mapTranscript}
                    onChange={(e) => setMapTranscript(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                  >
                    <option value="">(optional)</option>
                    {headers.map((h) => (
                      <option key={h} value={h}>{h}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Recording URL Column</label>
                  <select
                    value={mapRecordingUrl}
                    onChange={(e) => setMapRecordingUrl(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                  >
                    <option value="">(optional)</option>
                    {headers.map((h) => (
                      <option key={h} value={h}>{h}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <p className="text-sm font-medium text-gray-700">
                    Custom Columns
                    <span className="ml-2 text-xs font-normal text-gray-500">
                      Map CSV headers to your own field names
                    </span>
                  </p>
                  <button
                    type="button"
                    onClick={addCustomColumn}
                    disabled={uploadMutation.isPending}
                    className="inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:text-primary-900 disabled:opacity-50"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Add column
                  </button>
                </div>

                {customColumns.length === 0 ? (
                  <p className="text-xs text-gray-500">
                    No custom columns yet. Click "Add column" to create one.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {customColumns.map((row) => {
                      const trimmedName = row.name.trim().toLowerCase()
                      const duplicate =
                        !!trimmedName &&
                        customColumns.filter(
                          (other) => other.name.trim().toLowerCase() === trimmedName,
                        ).length > 1
                      return (
                        <div key={row.id} className="flex items-start gap-2">
                          <input
                            type="text"
                            value={row.name}
                            onChange={(e) =>
                              updateCustomColumn(row.id, { name: e.target.value })
                            }
                            placeholder="Custom name (e.g. agent_name)"
                            disabled={uploadMutation.isPending}
                            className={`flex-1 px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-primary-500 ${
                              duplicate ? 'border-red-300' : 'border-gray-300'
                            }`}
                          />
                          <select
                            value={row.csvHeader}
                            onChange={(e) =>
                              updateCustomColumn(row.id, { csvHeader: e.target.value })
                            }
                            disabled={uploadMutation.isPending}
                            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-primary-500"
                          >
                            <option value="">CSV column...</option>
                            {headers.map((h) => (
                              <option key={h} value={h}>
                                {h}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            onClick={() => removeCustomColumn(row.id)}
                            disabled={uploadMutation.isPending}
                            className="p-2 text-gray-400 hover:text-red-600 disabled:opacity-50"
                            aria-label="Remove custom column"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      )
                    })}
                    {!customNamesUnique && (
                      <p className="text-xs text-red-600">
                        Custom column names must be unique.
                      </p>
                    )}
                  </div>
                )}
              </div>

              {availableExtraColumns.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-gray-700 mb-1">Other columns to preserve</p>
                  <div className="flex flex-wrap gap-2">
                    {availableExtraColumns.map((column) => (
                      <button
                        key={column}
                        type="button"
                        onClick={() => toggleExtraColumn(column)}
                        className={`px-2.5 py-1 rounded-full border text-xs ${
                          extraColumns.includes(column)
                            ? 'bg-primary-600 border-primary-600 text-white'
                            : 'bg-white border-gray-300 text-gray-700'
                        }`}
                      >
                        {column}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <label htmlFor="csv-dataset" className="block text-sm font-medium text-gray-700 mb-1">
                  Dataset <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <input
                  id="csv-dataset"
                  type="text"
                  list="csv-dataset-suggestions"
                  value={dataset}
                  onChange={(e) => setDataset(e.target.value)}
                  disabled={uploadMutation.isPending}
                  placeholder="e.g., march-2026-batch"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:opacity-60"
                />
                <datalist id="csv-dataset-suggestions">
                  {existingDatasets.map((d) => (
                    <option key={d} value={d} />
                  ))}
                </datalist>
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
              Pick a provider + telephony credential first, then map CSV headers to:
              <code className="bg-blue-100 px-1 rounded ml-1">external_call_id</code>,
              <code className="bg-blue-100 px-1 rounded ml-1">transcript</code>,
              <code className="bg-blue-100 px-1 rounded ml-1">recording_url</code>.
            </p>
            <p>
              Use <strong>Custom Columns</strong> to give any other CSV column your own field
              name (e.g. <code className="bg-blue-100 px-1 rounded">agent_name</code>). They flow
              through to the evaluation CSV export under the name you choose.
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
