import PersonaPromptPanel from './PersonaPromptPanel'
import PersonaVoiceFields from './PersonaVoiceFields'
import PersonaTtsParamsPanel from './PersonaTtsParamsPanel'
import PersonaBehaviorPanel from './PersonaBehaviorPanel'
import type { PersonaFormData, PersonaTileTab, ProviderOption } from './personaTypes'

interface PersonaTabContentProps {
  tab: PersonaTileTab
  draft: PersonaFormData
  onChange: (next: PersonaFormData) => void
  providers: ProviderOption[]
  lockProvider: boolean
  voiceFieldSize?: 'sm' | 'md'
  promptEmbedded?: boolean
}

export default function PersonaTabContent({
  tab,
  draft,
  onChange,
  providers,
  lockProvider,
  voiceFieldSize = 'md',
  promptEmbedded = false,
}: PersonaTabContentProps) {
  if (tab === 'prompt') {
    return (
      <PersonaPromptPanel
        value={draft.description}
        onChange={(description) => onChange({ ...draft, description })}
        personaName={draft.name}
        personaGender={draft.gender}
        embedded={promptEmbedded}
      />
    )
  }

  if (tab === 'voice') {
    return (
      <PersonaVoiceFields
        draft={draft}
        onChange={onChange}
        providers={providers}
        lockProvider={lockProvider}
        size={voiceFieldSize}
      />
    )
  }

  if (tab === 'tts') {
    return (
      <PersonaTtsParamsPanel
        provider={draft.tts_provider}
        value={draft.tts_config}
        onChange={(tts_config) => onChange({ ...draft, tts_config })}
        embedded
      />
    )
  }

  return (
    <PersonaBehaviorPanel
      value={{
        llm_temperature: draft.llm_temperature,
        llm_max_tokens: draft.llm_max_tokens,
        response_delay_ms: draft.response_delay_ms,
        max_turns: draft.max_turns,
        allow_interruptions: draft.allow_interruptions,
      }}
      onChange={(behavior) =>
        onChange({
          ...draft,
          llm_temperature: behavior.llm_temperature ?? null,
          llm_max_tokens: behavior.llm_max_tokens ?? null,
          response_delay_ms: behavior.response_delay_ms ?? null,
          max_turns: behavior.max_turns ?? null,
          allow_interruptions: behavior.allow_interruptions ?? null,
        })
      }
      embedded
    />
  )
}
