export type PersonaParamKind = 'slider' | 'boolean' | 'select' | 'text'

export interface PersonaParamDef {
  key: string
  label: string
  kind: PersonaParamKind
  min?: number
  max?: number
  step?: number
  integer?: boolean
  helpText?: string
  options?: Array<{ value: string; label: string }>
  placeholder?: string
}

export const PERSONA_TTS_PARAMS: Record<string, PersonaParamDef[]> = {
  cartesia: [
    {
      key: 'speed',
      label: 'Speed (legacy models)',
      kind: 'select',
      helpText: 'For non-Sonic-3 models.',
      options: [
        { value: 'slow', label: 'Slow' },
        { value: 'normal', label: 'Normal' },
        { value: 'fast', label: 'Fast' },
      ],
    },
    {
      key: 'generation_config_speed',
      label: 'Speed (Sonic-3)',
      kind: 'slider',
      min: 0.6,
      max: 1.5,
      step: 0.05,
      helpText: 'Numeric speed multiplier for Sonic-3 models.',
    },
    {
      key: 'generation_config_volume',
      label: 'Volume (Sonic-3)',
      kind: 'slider',
      min: 0.5,
      max: 2.0,
      step: 0.05,
    },
    {
      key: 'generation_config_emotion',
      label: 'Emotion (Sonic-3)',
      kind: 'text',
      placeholder: 'e.g. neutral, excited, angry',
      helpText: 'Emotional tone guidance for Sonic-3 voices.',
    },
  ],
  elevenlabs: [
    { key: 'speed', label: 'Speed', kind: 'slider', min: 0.25, max: 4.0, step: 0.05 },
    { key: 'stability', label: 'Stability', kind: 'slider', min: 0, max: 1, step: 0.05, helpText: 'Lower = more expressive.' },
    { key: 'similarity_boost', label: 'Similarity boost', kind: 'slider', min: 0, max: 1, step: 0.05 },
    { key: 'style', label: 'Style', kind: 'slider', min: 0, max: 1, step: 0.05 },
    { key: 'use_speaker_boost', label: 'Speaker boost', kind: 'boolean' },
    {
      key: 'optimize_streaming_latency',
      label: 'Streaming latency optimization',
      kind: 'slider',
      min: 0,
      max: 4,
      step: 1,
      integer: true,
    },
    {
      key: 'apply_text_normalization',
      label: 'Text normalization',
      kind: 'select',
      options: [
        { value: 'auto', label: 'Auto' },
        { value: 'on', label: 'On' },
        { value: 'off', label: 'Off' },
      ],
    },
  ],
  openai: [
    { key: 'speed', label: 'Speed', kind: 'slider', min: 0.25, max: 4.0, step: 0.05 },
    {
      key: 'instructions',
      label: 'TTS acting instructions',
      kind: 'text',
      placeholder: 'Speak warmly and clearly...',
      helpText: 'How the voice delivers text — separate from the persona LLM prompt.',
    },
  ],
  sarvam: [
    { key: 'pace', label: 'Pace', kind: 'slider', min: 0.3, max: 3.0, step: 0.05 },
    { key: 'pitch', label: 'Pitch', kind: 'slider', min: -0.75, max: 0.75, step: 0.05 },
    { key: 'loudness', label: 'Loudness', kind: 'slider', min: 0.1, max: 3.0, step: 0.05 },
    { key: 'temperature', label: 'Temperature', kind: 'slider', min: 0.01, max: 1.0, step: 0.01, helpText: 'Synthesis variability (bulbul v3).' },
    { key: 'enable_preprocessing', label: 'Enable preprocessing', kind: 'boolean' },
  ],
  smallest: [
    { key: 'speed', label: 'Speed', kind: 'slider', min: 0.5, max: 2.0, step: 0.05 },
    { key: 'language', label: 'Language', kind: 'text', placeholder: 'en' },
  ],
  murf: [
    { key: 'speed', label: 'Speed', kind: 'slider', min: -50, max: 50, step: 1, integer: true },
    { key: 'pitch', label: 'Pitch', kind: 'slider', min: -50, max: 50, step: 1, integer: true },
    { key: 'style', label: 'Style', kind: 'text', placeholder: 'Optional style preset' },
  ],
  voicemaker: [
    { key: 'output_format', label: 'Output format', kind: 'text', placeholder: 'wav' },
  ],
}

export function getPersonaTtsParams(provider?: string | null): PersonaParamDef[] {
  if (!provider) return []
  return PERSONA_TTS_PARAMS[provider.toLowerCase()] ?? []
}

export function filterTtsConfigForProvider(
  provider: string | null | undefined,
  config: Record<string, unknown>,
): Record<string, unknown> {
  const allowed = new Set(getPersonaTtsParams(provider).map((p) => p.key))
  return Object.fromEntries(Object.entries(config).filter(([key]) => allowed.has(key)))
}
