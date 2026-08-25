import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, Mic } from 'lucide-react'
import ProviderLogo, { getProviderInfo } from '../../components/shared/ProviderLogo'
import { filterTtsConfigForProvider } from './personaTtsParams'
import {
  PERSONA_GENDERS,
  type PersonaFormData,
  type ProviderOption,
  type VoiceOption,
} from './personaTypes'

interface PersonaVoiceFieldsProps {
  draft: PersonaFormData
  onChange: (next: PersonaFormData) => void
  providers: ProviderOption[]
  lockProvider?: boolean
  size?: 'sm' | 'md'
}

export default function PersonaVoiceFields({
  draft,
  onChange,
  providers,
  lockProvider = false,
  size = 'sm',
}: PersonaVoiceFieldsProps) {
  const [voiceGenderFilter, setVoiceGenderFilter] = useState('all')
  const labelClass = size === 'md' ? 'text-sm font-medium text-gray-700' : 'text-xs font-medium text-gray-600'
  const inputClass =
    size === 'md'
      ? 'w-full px-3 py-2 text-sm border border-gray-300 rounded-lg appearance-none bg-white pr-8'
      : 'w-full px-3 py-2 text-sm border border-gray-300 rounded-lg appearance-none bg-white pr-8'

  const providerInfo = draft.tts_provider ? getProviderInfo(draft.tts_provider) : null

  const selectedProviderVoices = useMemo(() => {
    if (!draft.tts_provider) return []
    const provider = providers.find((p) => p.id === draft.tts_provider)
    if (!provider) return []
    if (voiceGenderFilter === 'all') return provider.voices
    return provider.voices.filter((v) => v.gender.toLowerCase() === voiceGenderFilter)
  }, [providers, draft.tts_provider, voiceGenderFilter])

  const handleVoiceSelect = (voice: VoiceOption) => {
    onChange({
      ...draft,
      tts_voice_id: voice.id,
      tts_voice_name: voice.name,
      gender: voice.gender.toLowerCase(),
      is_custom: voice.is_custom,
    })
  }

  return (
    <div className="space-y-4">
      <div>
        <label className={`block ${labelClass} mb-2`}>TTS provider</label>
        {lockProvider && draft.tts_provider ? (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 bg-gray-50">
            <ProviderLogo provider={draft.tts_provider} size="sm" />
            <span className="text-sm font-medium text-gray-800">
              {providerInfo?.label || draft.tts_provider}
            </span>
            <span className="text-xs text-gray-500 ml-auto">Locked after creation</span>
          </div>
        ) : providers.length === 0 ? (
          <p className="text-sm text-gray-600">
            No TTS providers are connected yet.{' '}
            <Link to="/integrations" className="text-primary-600 hover:text-primary-700 underline font-medium">
              Connect a provider in Integrations
            </Link>{' '}
            to choose a voice.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {providers.map((p) => {
              const isSelected = draft.tts_provider === p.id
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    const nextProvider = draft.tts_provider === p.id ? '' : p.id
                    onChange({
                      ...draft,
                      tts_provider: nextProvider,
                      tts_voice_id: draft.tts_provider === p.id ? '' : draft.tts_voice_id,
                      tts_voice_name: draft.tts_provider === p.id ? '' : draft.tts_voice_name,
                      tts_config: filterTtsConfigForProvider(nextProvider, draft.tts_config),
                    })
                    setVoiceGenderFilter('all')
                  }}
                  className={`flex items-center gap-2 px-2.5 py-2 rounded-lg border text-left transition-all ${
                    isSelected
                      ? 'border-primary-400 bg-primary-50 ring-1 ring-primary-200'
                      : 'border-gray-200 bg-white hover:border-gray-300'
                  }`}
                >
                  <ProviderLogo provider={p.id} size="sm" />
                  <span
                    className={`text-xs font-medium truncate ${isSelected ? 'text-primary-700' : 'text-gray-700'}`}
                  >
                    {p.name}
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {draft.tts_provider ? (
        <>
          <div>
            <label className={`block ${labelClass} mb-1`}>Filter voices</label>
            <div className="flex gap-1.5">
              {['all', 'male', 'female'].map((g) => (
                <button
                  key={g}
                  type="button"
                  onClick={() => setVoiceGenderFilter(g)}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-medium border ${
                    voiceGenderFilter === g
                      ? 'bg-primary-100 border-primary-300 text-primary-700'
                      : 'bg-white border-gray-300 text-gray-600'
                  }`}
                >
                  {g === 'all' ? 'All' : g.charAt(0).toUpperCase() + g.slice(1)}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className={`block ${labelClass} mb-1`}>
              Voice ({selectedProviderVoices.length})
            </label>
            <div className="max-h-36 overflow-y-auto border border-gray-200 rounded-lg divide-y divide-gray-100">
              {selectedProviderVoices.length === 0 ? (
                <p className="p-3 text-xs text-gray-500 text-center">No voices match filter</p>
              ) : (
                selectedProviderVoices.map((voice) => (
                  <button
                    key={voice.id}
                    type="button"
                    onClick={() => handleVoiceSelect(voice)}
                    className={`w-full flex items-center justify-between px-2.5 py-2 text-left text-xs hover:bg-gray-50 ${
                      draft.tts_voice_id === voice.id ? 'bg-primary-50 border-l-2 border-primary-500' : ''
                    }`}
                  >
                    <span className="font-medium text-gray-900 truncate flex items-center gap-1.5">
                      {size === 'md' ? <Mic className="h-3.5 w-3.5 text-gray-400 shrink-0" /> : null}
                      {voice.name}
                    </span>
                    <span className="text-gray-500 capitalize shrink-0 ml-2">{voice.gender}</span>
                  </button>
                ))
              )}
            </div>
          </div>
        </>
      ) : null}

      <div>
        <label className={`block ${labelClass} mb-1`}>Gender</label>
        <div className="relative">
          <select
            value={draft.gender}
            onChange={(e) => onChange({ ...draft, gender: e.target.value })}
            className={inputClass}
          >
            {PERSONA_GENDERS.map((g) => (
              <option key={g} value={g}>
                {g.charAt(0).toUpperCase() + g.slice(1)}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
        </div>
      </div>
    </div>
  )
}
