import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Volume2 } from 'lucide-react'
import { apiClient } from '../../lib/api'
import ParamSlider from '../agents/components/ParamSlider'
import AmbientPreviewControls from './AmbientPreviewControls'
import { useAmbientPreview } from './useAmbientPreview'

export interface PersonaAmbientValues {
  background_noise_source?: string | null
  background_noise_preset?: string | null
  background_noise_volume?: number | null
  background_noise_asset_id?: string | null
}

interface PersonaAmbientPanelProps {
  value: PersonaAmbientValues
  onChange: (next: PersonaAmbientValues) => void
  disabled?: boolean
  embedded?: boolean
}

const SOURCE_OPTIONS = [
  { id: 'none', label: 'None', description: 'No background noise on the caller mic.' },
  {
    id: 'platform',
    label: 'Platform preset',
    description: 'Built-in environments such as cafe, traffic, or office.',
  },
  {
    id: 'custom',
    label: 'Uploaded bed',
    description: 'Choose a loop from your workspace background noise library.',
  },
] as const

export default function PersonaAmbientPanel({
  value,
  onChange,
  disabled = false,
  embedded = false,
}: PersonaAmbientPanelProps) {
  const source = value.background_noise_source || 'none'
  const preview = useAmbientPreview()

  const { data: presetsData, isLoading: presetsLoading } = useQuery({
    queryKey: ['ambient-presets'],
    queryFn: () => apiClient.listAmbientPresets(),
    staleTime: 60_000,
  })

  const { data: library = [], isLoading: libraryLoading } = useQuery({
    queryKey: ['ambient-library'],
    queryFn: () => apiClient.listAmbientLibrary(),
    staleTime: 30_000,
  })

  const presets = presetsData?.presets ?? []
  const selectedPreset = value.background_noise_preset || presets[0]?.id || 'cafe'
  const selectedAssetId = value.background_noise_asset_id || library[0]?.id || ''

  useEffect(() => {
    return () => preview.stop()
  }, [preview])

  useEffect(() => {
    if (source === 'platform' && presets.length > 0 && !value.background_noise_preset) {
      onChange({ ...value, background_noise_preset: presets[0].id })
    }
  }, [source, presets, value, onChange])

  useEffect(() => {
    if (source === 'custom' && library.length > 0 && !value.background_noise_asset_id) {
      onChange({ ...value, background_noise_asset_id: library[0].id })
    }
  }, [source, library, value, onChange])

  const handleSourceChange = (nextSource: string) => {
    preview.stop()
    if (nextSource === 'none') {
      onChange({
        ...value,
        background_noise_source: 'none',
        background_noise_preset: null,
        background_noise_asset_id: null,
      })
      return
    }
    if (nextSource === 'platform') {
      onChange({
        ...value,
        background_noise_source: 'platform',
        background_noise_preset: selectedPreset,
        background_noise_asset_id: null,
      })
      return
    }
    onChange({
      ...value,
      background_noise_source: 'custom',
      background_noise_preset: null,
      background_noise_asset_id: selectedAssetId || null,
    })
  }

  const previewPreset = () => {
    if (!selectedPreset) return
    preview.togglePreview(`preset:${selectedPreset}`, () => apiClient.previewAmbientPreset(selectedPreset))
  }

  const previewAsset = () => {
    if (!selectedAssetId) return
    preview.togglePreview(`asset:${selectedAssetId}`, async () => {
      const { url } = await apiClient.getAmbientLibraryPreviewUrl(selectedAssetId)
      return url
    })
  }

  const renderPreviewControls = (previewId: string, onToggle: () => void) => {
    const active = preview.isActive(previewId)
    return (
      <AmbientPreviewControls
        previewId={previewId}
        onToggle={onToggle}
        currentTime={active ? preview.currentTime : 0}
        duration={active ? preview.duration : 0}
        onSeek={preview.seek}
        volume={preview.volume}
        onVolumeChange={preview.setVolume}
        isPlaying={preview.isPlaying(previewId)}
        isLoading={preview.isLoading(previewId)}
        isActive={active}
        disabled={disabled}
        compact
      />
    )
  }

  const inner = (
    <>
      {!embedded ? (
        <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Caller environment</p>
      ) : null}
      <p className="text-xs text-gray-500">
        Continuous background audio mixed into the test caller microphone during calls and playground sessions.
      </p>

      <div className="space-y-2">
        {SOURCE_OPTIONS.map((option) => (
          <label
            key={option.id}
            className={`flex items-start gap-3 rounded-lg border p-3 cursor-pointer transition-colors ${
              source === option.id
                ? 'border-primary-300 bg-primary-50/50'
                : 'border-gray-200 hover:border-gray-300'
            } ${disabled ? 'opacity-60 cursor-not-allowed' : ''}`}
          >
            <input
              type="radio"
              name="ambient-source"
              disabled={disabled}
              checked={source === option.id}
              onChange={() => handleSourceChange(option.id)}
              className="mt-0.5 h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-500"
            />
            <span>
              <span className="block text-sm font-medium text-gray-900">{option.label}</span>
              <span className="block text-xs text-gray-500 mt-0.5">{option.description}</span>
            </span>
          </label>
        ))}
      </div>

      {source === 'platform' ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50/60 p-4 space-y-3">
          <label className="block text-sm font-medium text-gray-800">Preset</label>
          {presetsLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading presets…
            </div>
          ) : presets.length === 0 ? (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-md px-3 py-2">
              No platform presets are installed yet. Upload a custom bed in the Background Noise tab, or install an
              ambient asset pack.
            </p>
          ) : (
            <div className="space-y-3">
              <select
                disabled={disabled}
                value={selectedPreset}
                onChange={(e) => {
                  preview.stop()
                  onChange({ ...value, background_noise_preset: e.target.value })
                }}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-primary-500 focus:ring-primary-500"
              >
                {presets.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.label}
                  </option>
                ))}
              </select>
              {renderPreviewControls(`preset:${selectedPreset}`, previewPreset)}
            </div>
          )}
        </div>
      ) : null}

      {source === 'custom' ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50/60 p-4 space-y-3">
          <label className="block text-sm font-medium text-gray-800">Uploaded bed</label>
          {libraryLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading library…
            </div>
          ) : library.length === 0 ? (
            <p className="text-xs text-gray-600 bg-white border border-gray-200 rounded-md px-3 py-2">
              No uploaded beds yet. Open the <span className="font-medium">Background Noise</span> tab on the Personas
              page to upload audio loops.
            </p>
          ) : (
            <div className="space-y-3">
              <select
                disabled={disabled}
                value={selectedAssetId}
                onChange={(e) => {
                  preview.stop()
                  onChange({ ...value, background_noise_asset_id: e.target.value })
                }}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-primary-500 focus:ring-primary-500"
              >
                {library.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {asset.name}
                  </option>
                ))}
              </select>
              {renderPreviewControls(`asset:${selectedAssetId}`, previewAsset)}
            </div>
          )}
        </div>
      ) : null}

      {source !== 'none' ? (
        <ParamSlider
          label="Ambient volume"
          min={0.05}
          max={0.6}
          step={0.01}
          disabled={disabled}
          value={value.background_noise_volume ?? 0.22}
          onChange={(background_noise_volume) => onChange({ ...value, background_noise_volume })}
          helpText="How loud the background bed sits under the caller voice."
        />
      ) : null}

      {preview.error ? (
        <p className="text-xs text-red-600 flex items-center gap-1.5">
          <Volume2 className="h-3.5 w-3.5 shrink-0" />
          {preview.error}
        </p>
      ) : null}
    </>
  )

  if (embedded) {
    return <div className="space-y-4">{inner}</div>
  }

  return (
    <div className="rounded-lg border border-emerald-100 bg-emerald-50/40 p-4 space-y-4">
      {inner}
    </div>
  )
}
