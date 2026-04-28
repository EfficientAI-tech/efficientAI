import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Upload, FileAudio, Mic, X, Volume2 } from 'lucide-react'
import { apiClient } from '../../../../lib/api'
import type { VoicePlaygroundSourceType } from '../../../../lib/api'
import ProviderLogo, { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import ProviderPanel from './ProviderPanel'
import { TTSVoice, TTSProvider } from '../types'

interface SourcePanelProps {
  label: string
  color: 'blue' | 'purple'
  providers: TTSProvider[]
  sourceType: VoicePlaygroundSourceType
  onSourceTypeChange: (t: VoicePlaygroundSourceType) => void
  // TTS props (forwarded to ProviderPanel)
  selectedProvider: string
  selectedModel: string
  selectedVoices: TTSVoice[]
  sampleRate: number | null
  onProviderChange: (p: string) => void
  onModelChange: (m: string) => void
  onVoicesChange: (v: TTSVoice[]) => void
  onSampleRateChange: (hz: number | null) => void
  // Recording / Upload props
  callImportRowIds: string[]
  onCallImportRowIdsChange: (ids: string[]) => void
  uploadKeys: string[]
  onUploadKeysChange: (keys: string[]) => void
}

const TAB_OPTIONS: Array<{ key: VoicePlaygroundSourceType; label: string; icon: any }> = [
  { key: 'tts', label: 'TTS Provider', icon: Volume2 },
  { key: 'recording', label: 'From Call Imports', icon: Mic },
  { key: 'upload', label: 'Upload Audio', icon: Upload },
]

export default function SourcePanel(props: SourcePanelProps) {
  const {
    label,
    color,
    providers,
    sourceType,
    onSourceTypeChange,
    selectedProvider,
    selectedModel,
    selectedVoices,
    sampleRate,
    onProviderChange,
    onModelChange,
    onVoicesChange,
    onSampleRateChange,
    callImportRowIds,
    onCallImportRowIdsChange,
    uploadKeys,
    onUploadKeysChange,
  } = props

  const tabActiveBg = color === 'blue' ? 'bg-blue-600 text-white' : 'bg-purple-600 text-white'
  const wrapperBg =
    color === 'blue'
      ? 'bg-gradient-to-br from-blue-50 to-sky-50 border-blue-200'
      : 'bg-gradient-to-br from-purple-50 to-fuchsia-50 border-purple-200'
  const accentText = color === 'blue' ? 'text-blue-900' : 'text-purple-900'
  const badgeBg = color === 'blue' ? 'bg-blue-600' : 'bg-purple-600'

  const showTTSBadge = sourceType === 'tts' && selectedProvider
  const sourceTypeLabel =
    sourceType === 'tts'
      ? 'TTS Provider'
      : sourceType === 'recording'
        ? 'Call Recording'
        : 'Uploaded Audio'

  return (
    <div className={`p-5 rounded-xl border-2 ${wrapperBg}`}>
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span
          className={`w-8 h-8 rounded-full ${badgeBg} text-white flex items-center justify-center text-sm font-bold`}
        >
          {label}
        </span>
        {showTTSBadge ? (
          <>
            <ProviderLogo provider={selectedProvider} size="md" />
            <span className={`font-semibold ${accentText}`}>
              {getProviderInfo(selectedProvider).label}
            </span>
            {selectedModel && (
              <span className="text-xs text-gray-600 bg-white/70 px-2 py-0.5 rounded-full border border-gray-200">
                {selectedModel}
              </span>
            )}
          </>
        ) : (
          <span className={`font-semibold ${accentText}`}>
            Side {label} · {sourceTypeLabel}
          </span>
        )}
      </div>
      <div className="flex gap-1.5 mb-4">
        {TAB_OPTIONS.map((opt) => {
          const active = sourceType === opt.key
          const Icon = opt.icon
          return (
            <button
              key={opt.key}
              onClick={() => onSourceTypeChange(opt.key)}
              className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg transition ${
                active ? tabActiveBg : 'bg-white text-gray-600 hover:bg-gray-50 border border-gray-200'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {opt.label}
            </button>
          )
        })}
      </div>

      {sourceType === 'tts' && (
        <ProviderPanel
          embedded
          label={label}
          color={color}
          providers={providers}
          selectedProvider={selectedProvider}
          selectedModel={selectedModel}
          selectedVoices={selectedVoices}
          sampleRate={sampleRate}
          onProviderChange={onProviderChange}
          onModelChange={onModelChange}
          onVoicesChange={onVoicesChange}
          onSampleRateChange={onSampleRateChange}
        />
      )}

      {sourceType === 'recording' && (
        <CallImportRowsPicker
          selectedIds={callImportRowIds}
          onChange={onCallImportRowIdsChange}
        />
      )}

      {sourceType === 'upload' && (
        <UploadAudioPicker uploadKeys={uploadKeys} onChange={onUploadKeysChange} />
      )}
    </div>
  )
}

function CallImportRowsPicker({
  selectedIds,
  onChange,
}: {
  selectedIds: string[]
  onChange: (ids: string[]) => void
}) {
  const [search, setSearch] = useState('')
  const [callImportFilter, setCallImportFilter] = useState<string>('')

  const { data, isLoading } = useQuery({
    queryKey: ['voice-playground-call-import-rows', callImportFilter],
    queryFn: () =>
      apiClient.listVoicePlaygroundCallImportRows({
        with_recording: true,
        limit: 200,
        ...(callImportFilter ? { call_import_id: callImportFilter } : {}),
      }),
  })

  const { data: callImportsList } = useQuery({
    queryKey: ['voice-playground-call-imports-list'],
    queryFn: () => apiClient.listCallImports({ page: 1, page_size: 50 }),
  })

  const rows = data?.items || []
  const filtered = useMemo(() => {
    if (!search.trim()) return rows
    const q = search.toLowerCase()
    return rows.filter(
      (r) =>
        r.external_call_id.toLowerCase().includes(q) ||
        (r.transcript || '').toLowerCase().includes(q) ||
        (r.call_import_filename || '').toLowerCase().includes(q),
    )
  }, [rows, search])

  const toggle = (id: string) => {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((x) => x !== id))
    } else {
      onChange([...selectedIds, id])
    }
  }

  const move = (idx: number, dir: -1 | 1) => {
    const next = [...selectedIds]
    const j = idx + dir
    if (j < 0 || j >= next.length) return
    ;[next[idx], next[j]] = [next[j], next[idx]]
    onChange(next)
  }

  const selectedRowsById = useMemo(() => {
    const map = new Map<string, (typeof rows)[number]>()
    for (const r of rows) map.set(r.id, r)
    return map
  }, [rows])

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-600">
        Pick one recording per sample text. The order below is the order they're paired with
        sample texts.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <select
          value={callImportFilter}
          onChange={(e) => setCallImportFilter(e.target.value)}
          className="px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white"
        >
          <option value="">All call imports</option>
          {(callImportsList?.items || []).map((ci: any) => (
            <option key={ci.id} value={ci.id}>
              {ci.original_filename || ci.id} ({ci.total_rows} rows)
            </option>
          ))}
        </select>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search call ID or transcript..."
          className="px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white"
        />
      </div>

      {selectedIds.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="px-3 py-2 text-xs font-medium text-gray-600 border-b border-gray-100">
            Selected ({selectedIds.length})
          </div>
          <ol className="divide-y divide-gray-100 text-sm">
            {selectedIds.map((id, idx) => {
              const r = selectedRowsById.get(id)
              return (
                <li key={id} className="px-3 py-2 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-gray-100 text-gray-600 text-xs flex items-center justify-center font-semibold">
                    {idx + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="truncate font-medium text-gray-800">
                      {r?.external_call_id || id}
                    </p>
                    {r?.transcript && (
                      <p className="truncate text-xs text-gray-500">{r.transcript}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => move(idx, -1)}
                      disabled={idx === 0}
                      className="px-1 text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30"
                    >
                      ↑
                    </button>
                    <button
                      onClick={() => move(idx, 1)}
                      disabled={idx === selectedIds.length - 1}
                      className="px-1 text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30"
                    >
                      ↓
                    </button>
                    <button
                      onClick={() => toggle(id)}
                      className="p-1 rounded hover:bg-red-50 text-red-500"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </li>
              )
            })}
          </ol>
        </div>
      )}

      <div className="rounded-lg border border-gray-200 bg-white max-h-72 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-6 text-sm text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading recordings...
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-6 text-sm text-gray-500">
            No recordings yet. Import a CSV in Call Imports first.
          </div>
        ) : (
          <ul className="divide-y divide-gray-100 text-sm">
            {filtered.map((r) => {
              const checked = selectedIds.includes(r.id)
              return (
                <li
                  key={r.id}
                  className={`px-3 py-2 flex items-center gap-2 cursor-pointer hover:bg-gray-50 ${
                    checked ? 'bg-blue-50' : ''
                  }`}
                  onClick={() => toggle(r.id)}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(r.id)}
                    onClick={(e) => e.stopPropagation()}
                    className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                  />
                  <div className="flex-1 min-w-0">
                    <p className="truncate font-medium text-gray-800">{r.external_call_id}</p>
                    {r.transcript && (
                      <p className="truncate text-xs text-gray-500">{r.transcript}</p>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}

function UploadAudioPicker({
  uploadKeys,
  onChange,
}: {
  uploadKeys: string[]
  onChange: (keys: string[]) => void
}) {
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploadInfo, setUploadInfo] = useState<Record<string, { filename: string; presigned_url: string | null }>>({})

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setIsUploading(true)
    setError(null)
    try {
      const results = await Promise.all(
        Array.from(files).map((f) => apiClient.uploadVoicePlaygroundAudio(f)),
      )
      const newKeys = results.map((r) => r.s3_key)
      const newInfo: typeof uploadInfo = { ...uploadInfo }
      results.forEach((r) => {
        newInfo[r.s3_key] = { filename: r.filename, presigned_url: r.presigned_url }
      })
      setUploadInfo(newInfo)
      onChange([...uploadKeys, ...newKeys])
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Upload failed')
    } finally {
      setIsUploading(false)
    }
  }

  const move = (idx: number, dir: -1 | 1) => {
    const next = [...uploadKeys]
    const j = idx + dir
    if (j < 0 || j >= next.length) return
    ;[next[idx], next[j]] = [next[j], next[idx]]
    onChange(next)
  }

  const remove = (key: string) => {
    onChange(uploadKeys.filter((k) => k !== key))
  }

  return (
    <div className="space-y-3">
      <label className="block w-full cursor-pointer rounded-lg border-2 border-dashed border-gray-300 bg-white p-6 text-center hover:bg-gray-50">
        <input
          type="file"
          accept="audio/*,.mp3,.wav,.flac,.ogg,.m4a,.aac,.webm"
          multiple
          onChange={(e) => handleFiles(e.target.files)}
          className="hidden"
        />
        {isUploading ? (
          <div className="flex items-center justify-center gap-2 text-sm text-gray-600">
            <Loader2 className="w-4 h-4 animate-spin" /> Uploading...
          </div>
        ) : (
          <div>
            <Upload className="w-6 h-6 mx-auto text-gray-400 mb-1" />
            <p className="text-sm text-gray-700 font-medium">Drop audio files or click to browse</p>
            <p className="text-xs text-gray-500">mp3, wav, flac, ogg, m4a · up to 25MB each</p>
          </div>
        )}
      </label>
      {error && <p className="text-xs text-red-600">{error}</p>}
      {uploadKeys.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="px-3 py-2 text-xs font-medium text-gray-600 border-b border-gray-100">
            Uploaded ({uploadKeys.length})
          </div>
          <ol className="divide-y divide-gray-100 text-sm">
            {uploadKeys.map((key, idx) => {
              const info = uploadInfo[key]
              return (
                <li key={key} className="px-3 py-2 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-gray-100 text-gray-600 text-xs flex items-center justify-center font-semibold">
                    {idx + 1}
                  </span>
                  <FileAudio className="w-4 h-4 text-gray-400 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="truncate text-gray-800">
                      {info?.filename || key.split('/').pop()}
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => move(idx, -1)}
                      disabled={idx === 0}
                      className="px-1 text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30"
                    >
                      ↑
                    </button>
                    <button
                      onClick={() => move(idx, 1)}
                      disabled={idx === uploadKeys.length - 1}
                      className="px-1 text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30"
                    >
                      ↓
                    </button>
                    <button
                      onClick={() => remove(key)}
                      className="p-1 rounded hover:bg-red-50 text-red-500"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </li>
              )
            })}
          </ol>
        </div>
      )}
    </div>
  )
}
