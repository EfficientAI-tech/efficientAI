export interface Persona {
  id: string
  name: string
  gender: string
  tts_provider?: string | null
  tts_voice_id?: string | null
  tts_voice_name?: string | null
  is_custom?: boolean
  description?: string | null
  tts_config?: Record<string, unknown> | null
  llm_temperature?: number | null
  llm_max_tokens?: number | null
  response_delay_ms?: number | null
  max_turns?: number | null
  allow_interruptions?: boolean | null
  background_noise_source?: string | null
  background_noise_preset?: string | null
  background_noise_volume?: number | null
  background_noise_s3_key?: string | null
  background_noise_asset_id?: string | null
  created_at: string
  updated_at: string
  created_by?: string | null
}

export interface PersonaFormData {
  name: string
  gender: string
  tts_provider: string
  tts_voice_id: string
  tts_voice_name: string
  is_custom: boolean
  description: string
  tts_config: Record<string, unknown>
  llm_temperature: number | null
  llm_max_tokens: number | null
  response_delay_ms: number | null
  max_turns: number | null
  allow_interruptions: boolean | null
  background_noise_source: string
  background_noise_preset: string | null
  background_noise_volume: number | null
  background_noise_s3_key: string | null
  background_noise_asset_id: string | null
}

export interface VoiceOption {
  id: string
  name: string
  gender: string
  is_custom: boolean
  custom_voice_id?: string
  description?: string | null
}

export interface ProviderOption {
  id: string
  name: string
  voices: VoiceOption[]
}

export const PERSONA_GENDERS = ['male', 'female', 'neutral'] as const

export type PersonaTileTab = 'prompt' | 'voice' | 'tts' | 'behavior' | 'environment'

export const PERSONA_TILE_TABS: { id: PersonaTileTab; label: string }[] = [
  { id: 'prompt', label: 'Prompt' },
  { id: 'voice', label: 'Voice' },
  { id: 'tts', label: 'TTS' },
  { id: 'behavior', label: 'Behavior' },
  { id: 'environment', label: 'Environment' },
]

export function emptyPersonaFormData(): PersonaFormData {
  return {
    name: '',
    gender: 'neutral',
    tts_provider: '',
    tts_voice_id: '',
    tts_voice_name: '',
    is_custom: false,
    description: '',
    tts_config: {},
    llm_temperature: null,
    llm_max_tokens: null,
    response_delay_ms: null,
    max_turns: null,
    allow_interruptions: null,
    background_noise_source: 'none',
    background_noise_preset: null,
    background_noise_volume: 0.22,
    background_noise_s3_key: null,
    background_noise_asset_id: null,
  }
}

export function personaToFormData(persona: Persona): PersonaFormData {
  return {
    name: persona.name,
    gender: persona.gender,
    tts_provider: persona.tts_provider || '',
    tts_voice_id: persona.tts_voice_id || '',
    tts_voice_name: persona.tts_voice_name || '',
    is_custom: persona.is_custom || false,
    description: persona.description || '',
    tts_config: { ...(persona.tts_config || {}) },
    llm_temperature: persona.llm_temperature ?? null,
    llm_max_tokens: persona.llm_max_tokens ?? null,
    response_delay_ms: persona.response_delay_ms ?? null,
    max_turns: persona.max_turns ?? null,
    allow_interruptions: persona.allow_interruptions ?? null,
    background_noise_source: persona.background_noise_source || 'none',
    background_noise_preset: persona.background_noise_preset ?? null,
    background_noise_volume: persona.background_noise_volume ?? 0.22,
    background_noise_s3_key: persona.background_noise_s3_key ?? null,
    background_noise_asset_id: persona.background_noise_asset_id ?? null,
  }
}

export function personaPayload(data: PersonaFormData) {
  return {
    name: data.name,
    gender: data.gender,
    tts_provider: data.tts_provider || undefined,
    tts_voice_id: data.tts_voice_id || undefined,
    tts_voice_name: data.tts_voice_name || undefined,
    is_custom: data.is_custom,
    description: data.description.trim() || undefined,
    tts_config: Object.keys(data.tts_config).length > 0 ? data.tts_config : undefined,
    llm_temperature: data.llm_temperature ?? undefined,
    llm_max_tokens: data.llm_max_tokens ?? undefined,
    response_delay_ms: data.response_delay_ms ?? undefined,
    max_turns: data.max_turns ?? undefined,
    allow_interruptions: data.allow_interruptions ?? undefined,
    background_noise_source: data.background_noise_source || 'none',
    background_noise_preset:
      data.background_noise_source === 'platform' ? data.background_noise_preset || 'cafe' : undefined,
    background_noise_volume: data.background_noise_volume ?? undefined,
    background_noise_asset_id:
      data.background_noise_source === 'custom' ? data.background_noise_asset_id || undefined : undefined,
  }
}

export function personaUpdatePayload(data: PersonaFormData, lockProvider: boolean) {
  const payload = personaPayload(data)
  if (lockProvider && data.tts_provider) {
    const { tts_provider: _ignored, ...rest } = payload
    if (payload.tts_config !== undefined) {
      return { ...rest, tts_provider: data.tts_provider }
    }
    return rest as ReturnType<typeof personaPayload>
  }
  return payload
}

export function formDataEquals(a: PersonaFormData, b: PersonaFormData): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

export function applyPersonaAmbientFields(
  form: PersonaFormData,
  persona: Partial<Persona>,
): PersonaFormData {
  return {
    ...form,
    background_noise_source: persona.background_noise_source || form.background_noise_source,
    background_noise_preset: persona.background_noise_preset ?? form.background_noise_preset,
    background_noise_volume: persona.background_noise_volume ?? form.background_noise_volume,
    background_noise_s3_key: persona.background_noise_s3_key ?? form.background_noise_s3_key,
    background_noise_asset_id: persona.background_noise_asset_id ?? form.background_noise_asset_id,
  }
}
