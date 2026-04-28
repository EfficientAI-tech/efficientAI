import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Plus, X, Mic, Upload, Volume2, FileAudio, Play, Pause } from 'lucide-react'
import { apiClient } from '../../../../lib/api'
import type {
  VoicePlaygroundBlindTestAudioRef,
  VoicePlaygroundBlindTestRefType,
} from '../../../../lib/api'
import { useVoicePlayground } from '../context'
import type { BlindTestPairDraft } from '../context/VoicePlaygroundContext'
import Button from '../../../../components/Button'

type RefType = VoicePlaygroundBlindTestRefType

const REF_TYPES: Array<{ key: RefType; label: string; icon: any }> = [
  { key: 'recording', label: 'Recording', icon: Mic },
  { key: 'upload', label: 'Upload', icon: Upload },
  { key: 'tts_sample', label: 'Past TTS', icon: Volume2 },
]

export default function BlindTestOnlyConfig() {
  const {
    blindTestPairs,
    addBlindTestPair,
    removeBlindTestPair,
    updateBlindTestPair,
    canRun,
    createComparison,
    isCreating,
  } = useVoicePlayground()

  return (
    <div className="bg-gradient-to-br from-purple-50 to-fuchsia-50 rounded-xl border-2 border-purple-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-purple-900">Blind Test Pairs</h3>
          <p className="text-xs text-purple-700 mt-1">
            Each pair will be played as X vs Y to your raters. You can mix recordings, uploads, and
            past TTS samples freely.
          </p>
        </div>
        <Button
          variant="secondary"
          leftIcon={<Plus className="w-4 h-4" />}
          onClick={addBlindTestPair}
        >
          Add Pair
        </Button>
      </div>

      <div className="space-y-4">
        {blindTestPairs.map((pair, idx) => (
          <PairRow
            key={pair.id}
            index={idx}
            pair={pair}
            onUpdate={(updates) => updateBlindTestPair(pair.id, updates)}
            onRemove={blindTestPairs.length > 1 ? () => removeBlindTestPair(pair.id) : undefined}
          />
        ))}
      </div>

      <div className="mt-6 flex justify-center">
        <Button
          variant="primary"
          size="lg"
          onClick={createComparison}
          disabled={!canRun || isCreating}
          leftIcon={isCreating ? <Loader2 className="w-5 h-5 animate-spin" /> : undefined}
          className="px-12"
        >
          {isCreating ? 'Creating...' : 'Create Blind Test'}
        </Button>
      </div>
    </div>
  )
}

function PairRow({
  index,
  pair,
  onUpdate,
  onRemove,
}: {
  index: number
  pair: BlindTestPairDraft
  onUpdate: (updates: Partial<BlindTestPairDraft>) => void
  onRemove?: () => void
}) {
  return (
    <div className="rounded-xl border border-purple-200 bg-white p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="w-7 h-7 rounded-full bg-purple-600 text-white text-sm font-bold flex items-center justify-center">
            {index + 1}
          </span>
          <span className="text-sm font-semibold text-gray-800">Pair {index + 1}</span>
        </div>
        {onRemove && (
          <button
            onClick={onRemove}
            className="p-1 rounded hover:bg-red-50 text-red-500"
            title="Remove pair"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      <input
        type="text"
        value={pair.text}
        onChange={(e) => onUpdate({ text: e.target.value })}
        placeholder="Optional label or transcript for this pair..."
        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg mb-3"
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <AudioRefPicker
          label="X"
          color="blue"
          value={pair.x}
          onChange={(ref) => onUpdate({ x: ref })}
        />
        <AudioRefPicker
          label="Y"
          color="purple"
          value={pair.y}
          onChange={(ref) => onUpdate({ y: ref })}
        />
      </div>
    </div>
  )
}

function AudioRefPicker({
  label,
  color,
  value,
  onChange,
}: {
  label: string
  color: 'blue' | 'purple'
  value: VoicePlaygroundBlindTestAudioRef | null
  onChange: (ref: VoicePlaygroundBlindTestAudioRef | null) => void
}) {
  const [type, setType] = useState<RefType>(value?.type || 'recording')

  useEffect(() => {
    if (value?.type) setType(value.type)
  }, [value?.type])

  const headerBg = color === 'blue' ? 'bg-blue-600' : 'bg-purple-600'

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
      <div className="flex items-center gap-2 mb-2">
        <span
          className={`w-6 h-6 rounded-full ${headerBg} text-white text-xs font-bold flex items-center justify-center`}
        >
          {label}
        </span>
        <span className="text-sm font-medium text-gray-700">Audio source</span>
      </div>

      <div className="flex gap-1 mb-3">
        {REF_TYPES.map((rt) => {
          const Icon = rt.icon
          const active = type === rt.key
          return (
            <button
              key={rt.key}
              onClick={() => {
                setType(rt.key)
                if (value?.type !== rt.key) onChange(null)
              }}
              className={`flex-1 inline-flex items-center justify-center gap-1 px-2 py-1.5 text-xs rounded-md border transition ${
                active
                  ? 'bg-gray-900 text-white border-gray-900'
                  : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
              }`}
            >
              <Icon className="w-3 h-3" />
              {rt.label}
            </button>
          )
        })}
      </div>

      {type === 'recording' && (
        <RecordingPicker
          selectedId={value?.type === 'recording' ? value.call_import_row_id : undefined}
          onSelect={(rowId, label) =>
            onChange(rowId ? { type: 'recording', call_import_row_id: rowId, label } : null)
          }
        />
      )}
      {type === 'upload' && (
        <UploadPicker
          selectedKey={value?.type === 'upload' ? value.upload_s3_key : undefined}
          selectedLabel={value?.type === 'upload' ? value.label : undefined}
          onSelect={(key, label) =>
            onChange(key ? { type: 'upload', upload_s3_key: key, label } : null)
          }
        />
      )}
      {type === 'tts_sample' && (
        <PastTTSPicker
          selectedSampleId={value?.type === 'tts_sample' ? value.tts_sample_id : undefined}
          onSelect={(sampleId, label) =>
            onChange(sampleId ? { type: 'tts_sample', tts_sample_id: sampleId, label } : null)
          }
        />
      )}
    </div>
  )
}

function RecordingPicker({
  selectedId,
  onSelect,
}: {
  selectedId?: string
  onSelect: (id: string | null, label?: string) => void
}) {
  const [search, setSearch] = useState('')
  const [callImportFilter, setCallImportFilter] = useState<string>('')

  const { data, isLoading } = useQuery({
    queryKey: ['blind-test-only-call-import-rows', callImportFilter],
    queryFn: () =>
      apiClient.listVoicePlaygroundCallImportRows({
        with_recording: true,
        limit: 200,
        ...(callImportFilter ? { call_import_id: callImportFilter } : {}),
      }),
  })
  const { data: callImportsList } = useQuery({
    queryKey: ['blind-test-only-call-imports-list'],
    queryFn: () => apiClient.listCallImports({ page: 1, page_size: 50 }),
  })

  const rows = data?.items || []
  const filtered = useMemo(() => {
    if (!search.trim()) return rows
    const q = search.toLowerCase()
    return rows.filter(
      (r: any) =>
        r.external_call_id?.toLowerCase().includes(q) ||
        (r.transcript || '').toLowerCase().includes(q),
    )
  }, [rows, search])

  const selectedRow = rows.find((r: any) => r.id === selectedId)

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 gap-2">
        <select
          value={callImportFilter}
          onChange={(e) => setCallImportFilter(e.target.value)}
          className="px-2 py-1.5 text-xs border border-gray-300 rounded bg-white"
        >
          <option value="">All call imports</option>
          {(callImportsList?.items || []).map((ci: any) => (
            <option key={ci.id} value={ci.id}>
              {ci.original_filename || ci.id}
            </option>
          ))}
        </select>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search call ID or transcript..."
          className="px-2 py-1.5 text-xs border border-gray-300 rounded bg-white"
        />
      </div>

      {selectedRow && (
        <div className="rounded border border-blue-200 bg-blue-50 px-2 py-1.5 flex items-center justify-between">
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-blue-900">
              {selectedRow.external_call_id || selectedId}
            </p>
            {selectedRow.transcript && (
              <p className="truncate text-[11px] text-blue-700">{selectedRow.transcript}</p>
            )}
          </div>
          <button
            onClick={() => onSelect(null)}
            className="ml-2 p-1 rounded hover:bg-red-100 text-red-500"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      <div className="max-h-44 overflow-y-auto rounded border border-gray-200 bg-white">
        {isLoading ? (
          <div className="flex items-center justify-center py-4 text-xs text-gray-500">
            <Loader2 className="w-3 h-3 animate-spin mr-1.5" /> Loading...
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-4 text-xs text-gray-500">No recordings found</div>
        ) : (
          <ul className="divide-y divide-gray-100 text-xs">
            {filtered.map((r: any) => {
              const active = r.id === selectedId
              return (
                <li
                  key={r.id}
                  onClick={() => onSelect(r.id, r.external_call_id || undefined)}
                  className={`px-2 py-1.5 cursor-pointer hover:bg-gray-50 ${
                    active ? 'bg-blue-50' : ''
                  }`}
                >
                  <p className="truncate font-medium text-gray-800">{r.external_call_id}</p>
                  {r.transcript && (
                    <p className="truncate text-[11px] text-gray-500">{r.transcript}</p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}

function UploadPicker({
  selectedKey,
  selectedLabel,
  onSelect,
}: {
  selectedKey?: string
  selectedLabel?: string
  onSelect: (key: string | null, label?: string) => void
}) {
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleFile = async (file: File | null) => {
    if (!file) return
    setIsUploading(true)
    setError(null)
    try {
      const result = await apiClient.uploadVoicePlaygroundAudio(file)
      onSelect(result.s3_key, result.filename)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Upload failed')
    } finally {
      setIsUploading(false)
    }
  }

  if (selectedKey) {
    return (
      <div className="rounded border border-purple-200 bg-purple-50 px-2 py-1.5 flex items-center gap-2">
        <FileAudio className="w-3.5 h-3.5 text-purple-600 flex-shrink-0" />
        <p className="flex-1 truncate text-xs font-medium text-purple-900">
          {selectedLabel || selectedKey.split('/').pop()}
        </p>
        <button
          onClick={() => onSelect(null)}
          className="p-1 rounded hover:bg-red-100 text-red-500"
        >
          <X className="w-3 h-3" />
        </button>
      </div>
    )
  }

  return (
    <div>
      <label className="block w-full cursor-pointer rounded-lg border-2 border-dashed border-gray-300 bg-white px-3 py-4 text-center hover:bg-gray-50">
        <input
          type="file"
          accept="audio/*,.mp3,.wav,.flac,.ogg,.m4a,.aac,.webm"
          onChange={(e) => handleFile(e.target.files?.[0] || null)}
          className="hidden"
        />
        {isUploading ? (
          <div className="flex items-center justify-center gap-1.5 text-xs text-gray-600">
            <Loader2 className="w-3 h-3 animate-spin" /> Uploading...
          </div>
        ) : (
          <div>
            <Upload className="w-4 h-4 mx-auto text-gray-400 mb-0.5" />
            <p className="text-xs text-gray-700 font-medium">Click to upload audio</p>
            <p className="text-[11px] text-gray-500">mp3, wav, flac · up to 25MB</p>
          </div>
        )}
      </label>
      {error && <p className="mt-1 text-[11px] text-red-600">{error}</p>}
    </div>
  )
}

function PastTTSPicker({
  selectedSampleId,
  onSelect,
}: {
  selectedSampleId?: string
  onSelect: (sampleId: string | null, label?: string) => void
}) {
  const [search, setSearch] = useState('')
  const [activeComparisonId, setActiveComparisonId] = useState<string>('')
  const [previewingId, setPreviewingId] = useState<string | null>(null)
  const [previewAudio, setPreviewAudio] = useState<HTMLAudioElement | null>(null)

  const { data: comparisons = [] } = useQuery({
    queryKey: ['past-tts-comparisons-list'],
    queryFn: () => apiClient.listTTSComparisons(0, 50),
  })

  const { data: comparisonDetail } = useQuery({
    queryKey: ['past-tts-comparison-detail', activeComparisonId],
    queryFn: () => apiClient.getTTSComparison(activeComparisonId),
    enabled: !!activeComparisonId,
  })

  const samples: any[] = useMemo(() => {
    const s = (comparisonDetail?.samples || []) as any[]
    return s.filter((x) => x.audio_url || x.audio_s3_key)
  }, [comparisonDetail])

  const filtered = useMemo(() => {
    if (!search.trim()) return samples
    const q = search.toLowerCase()
    return samples.filter(
      (s) =>
        (s.text || '').toLowerCase().includes(q) ||
        (s.voice_name || '').toLowerCase().includes(q) ||
        (s.provider || '').toLowerCase().includes(q),
    )
  }, [samples, search])

  const selectedSample = samples.find((s) => s.id === selectedSampleId)

  const togglePreview = (sample: any) => {
    if (previewingId === sample.id) {
      previewAudio?.pause()
      setPreviewingId(null)
      setPreviewAudio(null)
      return
    }
    previewAudio?.pause()
    const url = sample.audio_url
    if (!url) return
    const audio = new Audio(url)
    audio.onended = () => {
      setPreviewingId(null)
      setPreviewAudio(null)
    }
    audio.play()
    setPreviewingId(sample.id)
    setPreviewAudio(audio)
  }

  return (
    <div className="space-y-2">
      <select
        value={activeComparisonId}
        onChange={(e) => setActiveComparisonId(e.target.value)}
        className="w-full px-2 py-1.5 text-xs border border-gray-300 rounded bg-white"
      >
        <option value="">Select past comparison...</option>
        {comparisons.map((c: any) => (
          <option key={c.id} value={c.id}>
            {c.name || c.id}
          </option>
        ))}
      </select>

      {activeComparisonId && (
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by text, voice, or provider..."
          className="w-full px-2 py-1.5 text-xs border border-gray-300 rounded bg-white"
        />
      )}

      {selectedSample && (
        <div className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1.5 flex items-center gap-2">
          <Volume2 className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="truncate text-xs font-medium text-emerald-900">
              {selectedSample.voice_name || selectedSample.id}
            </p>
            {selectedSample.text && (
              <p className="truncate text-[11px] text-emerald-700">{selectedSample.text}</p>
            )}
          </div>
          <button
            onClick={() => onSelect(null)}
            className="p-1 rounded hover:bg-red-100 text-red-500"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {activeComparisonId && (
        <div className="max-h-44 overflow-y-auto rounded border border-gray-200 bg-white">
          {filtered.length === 0 ? (
            <div className="text-center py-4 text-xs text-gray-500">No completed samples</div>
          ) : (
            <ul className="divide-y divide-gray-100 text-xs">
              {filtered.map((s) => {
                const active = s.id === selectedSampleId
                return (
                  <li
                    key={s.id}
                    className={`px-2 py-1.5 hover:bg-gray-50 ${active ? 'bg-emerald-50' : ''}`}
                  >
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => togglePreview(s)}
                        className="p-1 rounded hover:bg-gray-100 text-gray-600 flex-shrink-0"
                        disabled={!s.audio_url}
                      >
                        {previewingId === s.id ? (
                          <Pause className="w-3 h-3" />
                        ) : (
                          <Play className="w-3 h-3" />
                        )}
                      </button>
                      <button
                        onClick={() =>
                          onSelect(
                            s.id,
                            `${s.voice_name || s.provider} • ${(s.text || '').slice(0, 30)}`,
                          )
                        }
                        className="flex-1 min-w-0 text-left"
                      >
                        <p className="truncate font-medium text-gray-800">
                          {s.voice_name || s.provider} {s.side ? `(side ${s.side})` : ''}
                        </p>
                        {s.text && (
                          <p className="truncate text-[11px] text-gray-500">{s.text}</p>
                        )}
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
