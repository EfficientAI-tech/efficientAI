/** Provider-aware visibility for LLM advanced generation parameters. */

export type LLMGenerationParamKey =
  | 'temperature'
  | 'max_tokens'
  | 'top_p'
  | 'top_k'
  | 'frequency_penalty'
  | 'presence_penalty'
  | 'seed'

export interface LLMGenerationParamMeta {
  key: LLMGenerationParamKey
  label: string
  min?: number
  max?: number
  step?: number
  integer?: boolean
  placeholder?: string
  helpText?: string
}

export interface LLMGenerationConfig {
  temperature?: number | null
  max_tokens?: number | null
  top_p?: number | null
  top_k?: number | null
  frequency_penalty?: number | null
  presence_penalty?: number | null
  seed?: number | null
}

const COMMON_PARAMS: LLMGenerationParamMeta[] = [
  {
    key: 'temperature',
    label: 'Temperature',
    min: 0,
    max: 2,
    step: 0.1,
    placeholder: 'Default',
    helpText: 'Higher values make output more random; lower values more focused.',
  },
  {
    key: 'max_tokens',
    label: 'Max Tokens',
    min: 1,
    step: 1,
    integer: true,
    placeholder: 'Default',
    helpText: 'Maximum number of tokens to generate.',
  },
  {
    key: 'top_p',
    label: 'Top P',
    min: 0,
    max: 1,
    step: 0.05,
    placeholder: 'Default',
    helpText: 'Nucleus sampling: consider tokens with cumulative probability up to this value.',
  },
  {
    key: 'top_k',
    label: 'Top K',
    min: 0,
    step: 1,
    integer: true,
    placeholder: 'Default',
    helpText: 'Limit sampling to the K most likely next tokens.',
  },
  {
    key: 'frequency_penalty',
    label: 'Frequency Penalty',
    min: -2,
    max: 2,
    step: 0.1,
    placeholder: 'Default',
  },
  {
    key: 'presence_penalty',
    label: 'Presence Penalty',
    min: -2,
    max: 2,
    step: 0.1,
    placeholder: 'Default',
  },
  {
    key: 'seed',
    label: 'Seed',
    min: 0,
    step: 1,
    integer: true,
    placeholder: 'Default',
    helpText: 'Random seed for reproducible outputs (when supported).',
  },
]

/** Providers that ignore top_k at the API level. */
const NO_TOP_K = new Set([
  'openai',
  'azure',
  'groq',
  'deepseek',
  'xai',
  'fireworks',
  'openrouter',
  'cohere',
  'mistral',
  'meta',
  'together',
  'perplexity',
  'aws',
])

/** Anthropic caps temperature at 1.0. */
const TEMP_MAX_1 = new Set(['anthropic'])

/** Providers without OpenAI-style frequency/presence penalties. */
const NO_PENALTIES = new Set(['anthropic', 'google'])

export function getVisibleLLMParams(provider: string | null | undefined): LLMGenerationParamMeta[] {
  const key = (provider || '').toLowerCase()
  return COMMON_PARAMS.filter((param) => {
    if (param.key === 'top_k' && NO_TOP_K.has(key)) return false
    if (
      (param.key === 'frequency_penalty' || param.key === 'presence_penalty') &&
      NO_PENALTIES.has(key)
    ) {
      return false
    }
    return true
  }).map((param) => {
    if (param.key === 'temperature' && TEMP_MAX_1.has(key)) {
      return { ...param, max: 1 }
    }
    return param
  })
}

export function isLLMGenerationConfigEmpty(
  config: LLMGenerationConfig | null | undefined,
): boolean {
  if (!config) return true
  return !Object.values(config).some((v) => v !== null && v !== undefined && v !== '')
}

export function summarizeLLMConfig(
  config: LLMGenerationConfig | null | undefined,
): string {
  if (!config || isLLMGenerationConfigEmpty(config)) return ''
  const parts: string[] = []
  if (config.temperature != null) parts.push(`temp ${config.temperature}`)
  if (config.top_p != null) parts.push(`top_p ${config.top_p}`)
  if (config.top_k != null) parts.push(`top_k ${config.top_k}`)
  if (config.max_tokens != null) parts.push(`max ${config.max_tokens}`)
  return parts.slice(0, 3).join(' · ')
}

export function normalizeLLMConfig(
  config: LLMGenerationConfig | null | undefined,
): LLMGenerationConfig | null {
  if (!config) return null
  const cleaned: LLMGenerationConfig = {}
  for (const [key, value] of Object.entries(config)) {
    if (value === null || value === undefined || value === '') continue
    ;(cleaned as Record<string, number>)[key] = Number(value)
  }
  return isLLMGenerationConfigEmpty(cleaned) ? null : cleaned
}
