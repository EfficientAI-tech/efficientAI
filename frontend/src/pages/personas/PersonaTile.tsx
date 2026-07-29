import { useEffect, useMemo, useState } from 'react'
import { Mic, Save, Trash2 } from 'lucide-react'
import Button from '../../components/Button'
import ProviderLogo, { getProviderInfo } from '../../components/shared/ProviderLogo'
import PersonaTtsParamsPanel from './PersonaTtsParamsPanel'
import PersonaBehaviorPanel from './PersonaBehaviorPanel'
import PersonaPromptPanel from './PersonaPromptPanel'
import PersonaVoiceFields from './PersonaVoiceFields'
import {
  PERSONA_TILE_TABS,
  personaToFormData,
  type Persona,
  type PersonaFormData,
  type PersonaTileTab,
  type ProviderOption,
  formDataEquals,
} from './personaTypes'

interface PersonaTileProps {
  persona: Persona
  providers: ProviderOption[]
  onSave: (id: string, data: PersonaFormData) => void
  onDelete: (persona: Persona) => void
  isSaving?: boolean
}

export default function PersonaTile({
  persona,
  providers,
  onSave,
  onDelete,
  isSaving = false,
}: PersonaTileProps) {
  const [activeTab, setActiveTab] = useState<PersonaTileTab>('prompt')
  const [draft, setDraft] = useState<PersonaFormData>(() => personaToFormData(persona))

  useEffect(() => {
    setDraft(personaToFormData(persona))
  }, [persona.id, persona.updated_at])

  const baseline = useMemo(() => personaToFormData(persona), [persona])
  const isDirty = !formDataEquals(draft, baseline)
  const lockProvider = Boolean(persona.tts_provider)

  const providerInfo = draft.tts_provider ? getProviderInfo(draft.tts_provider) : null

  const handleSave = () => {
    onSave(persona.id, draft)
  }

  const handleDiscard = () => {
    setDraft(baseline)
  }

  return (
    <article className="bg-white rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow flex flex-col min-h-[420px] overflow-hidden">
      {/* Tile header */}
      <div className="px-4 pt-4 pb-3 border-b border-gray-100 bg-gradient-to-br from-gray-50/80 to-white">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <input
              type="text"
              value={draft.name}
              onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))}
              className="w-full text-base font-semibold text-gray-900 bg-transparent border-0 border-b border-transparent hover:border-gray-200 focus:border-primary-400 focus:ring-0 px-0 py-0.5 truncate"
              aria-label="Persona name"
            />
            <div className="flex flex-wrap items-center gap-2 mt-2">
              {draft.tts_provider ? (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-white border border-gray-200 text-xs text-gray-700">
                  <ProviderLogo provider={draft.tts_provider} size="sm" />
                  {providerInfo?.label || draft.tts_provider}
                </span>
              ) : (
                <span className="text-xs text-gray-400">No provider</span>
              )}
              {draft.tts_voice_name ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary-50 text-xs text-primary-700">
                  <Mic className="h-3 w-3" />
                  {draft.tts_voice_name}
                </span>
              ) : null}
              <span className="inline-flex px-2 py-0.5 rounded-full bg-gray-100 text-xs text-gray-600 capitalize">
                {draft.gender}
              </span>
              {draft.is_custom ? (
                <span className="px-1.5 py-0.5 text-[10px] font-medium bg-amber-100 text-amber-700 rounded">
                  Custom voice
                </span>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            onClick={() => onDelete(persona)}
            className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors shrink-0"
            title="Delete persona"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Sub-tabs */}
      <div className="px-3 pt-2 border-b border-gray-100">
        <nav className="flex gap-1 overflow-x-auto" aria-label={`${persona.name} settings`}>
          {PERSONA_TILE_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`whitespace-nowrap px-3 py-2 text-xs font-medium rounded-t-lg border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-primary-500 text-primary-700 bg-primary-50/60'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      <div className="flex-1 p-4 overflow-y-auto max-h-72">
        {activeTab === 'prompt' && (
          <PersonaPromptPanel
            value={draft.description}
            onChange={(description) => setDraft((p) => ({ ...p, description }))}
            personaName={draft.name}
            personaGender={draft.gender}
            embedded
          />
        )}

        {activeTab === 'voice' && (
          <PersonaVoiceFields
            draft={draft}
            onChange={setDraft}
            providers={providers}
            lockProvider={lockProvider}
          />
        )}

        {activeTab === 'tts' && (
          <PersonaTtsParamsPanel
            provider={draft.tts_provider}
            value={draft.tts_config}
            onChange={(tts_config) => setDraft((p) => ({ ...p, tts_config }))}
            embedded
          />
        )}

        {activeTab === 'behavior' && (
          <PersonaBehaviorPanel
            value={{
              llm_temperature: draft.llm_temperature,
              llm_max_tokens: draft.llm_max_tokens,
              response_delay_ms: draft.response_delay_ms,
              max_turns: draft.max_turns,
              allow_interruptions: draft.allow_interruptions,
            }}
            onChange={(behavior) =>
              setDraft((p) => ({
                ...p,
                llm_temperature: behavior.llm_temperature ?? null,
                llm_max_tokens: behavior.llm_max_tokens ?? null,
                response_delay_ms: behavior.response_delay_ms ?? null,
                max_turns: behavior.max_turns ?? null,
                allow_interruptions: behavior.allow_interruptions ?? null,
              }))
            }
            embedded
          />
        )}
      </div>

      {/* Tile footer */}
      <div className="px-4 py-3 border-t border-gray-100 bg-gray-50/50 flex items-center justify-between gap-2">
        <span className="text-[11px] text-gray-400">
          {isDirty ? 'Unsaved changes' : 'Up to date'}
        </span>
        <div className="flex gap-2">
          {isDirty ? (
            <Button type="button" variant="ghost" size="sm" onClick={handleDiscard} disabled={isSaving}>
              Discard
            </Button>
          ) : null}
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={handleSave}
            isLoading={isSaving}
            disabled={!isDirty || !draft.name.trim() || isSaving}
            leftIcon={!isSaving ? <Save className="h-3.5 w-3.5" /> : undefined}
          >
            Save
          </Button>
        </div>
      </div>
    </article>
  )
}
