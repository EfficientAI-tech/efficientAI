/**
 * Shared provider+model picker used wherever the user has to choose an
 * AI Provider (LLM or STT) plus a model from the org's configured
 * credentials. Wraps the `listAIProviders` + `getModelOptions(provider)`
 * pair that several pages (PromptPartials, Scenarios, EvaluatorDetail,
 * VoiceBundles) had open-coded with slight variations.
 *
 * The component is intentionally headless about *what kind* of model
 * we're picking — pass `kind="stt"` to filter `getModelOptions` to the
 * `stt` array, or `kind="llm"` for the `llm` array. The UI labels and
 * empty-state hints adjust accordingly.
 *
 * Credentials live in two tables in this codebase:
 *   - `AIProvider`  — LLM-style providers (OpenAI, Anthropic, …)
 *   - `Integration` — voice / STT platforms (Deepgram, Sarvam, Smallest,
 *     ElevenLabs, etc.) added via Configurations → Integrations
 * Backend STT resolution (`TranscriptionService._get_api_key_for_provider`)
 * already checks both tables, so the picker has to merge them too —
 * otherwise users who configured Deepgram under "Voice Platforms"
 * would see only OpenAI as an STT option.
 *
 * `value` may be partially filled (provider only, no model) so callers
 * can implement an "Auto" / "Use run default" affordance by clearing
 * both fields.
 */
import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bot, AudioLines } from 'lucide-react'

import { apiClient } from '../../lib/api'
import type { Integration } from '../../types/api'

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  openrouter: 'OpenRouter',
  xai: 'xAI',
  google: 'Google',
  cohere: 'Cohere',
  mistral: 'Mistral',
  meta: 'Meta',
  together: 'Together',
  perplexity: 'Perplexity',
  azure: 'Azure',
  aws: 'AWS',
  deepgram: 'Deepgram',
  elevenlabs: 'ElevenLabs',
  sarvam: 'Sarvam',
  smallest: 'Smallest',
}

export interface ProviderModelValue {
  provider: string | null
  model: string | null
  credential_id?: string | null
}

interface AIProviderRow {
  id: string
  provider: string
  is_active: boolean
  is_default?: boolean
  name?: string | null
}

/** Origin of a credential row, used for de-duplication + tooltip copy. */
type CredentialSource = 'aiprovider' | 'integration'

interface CredentialRow {
  id: string
  /** Lower-cased provider key — e.g. "openai", "deepgram". */
  provider: string
  is_active: boolean
  is_default?: boolean
  name?: string | null
  source: CredentialSource
}

export interface ProviderModelPickerProps {
  /** Which model array to use from `getModelOptions` (also drives icons / labels). */
  kind: 'llm' | 'stt'
  value: ProviderModelValue
  onChange: (next: ProviderModelValue) => void
  /** Restrict providers to this allow-list (lower-cased). Useful for STT (only some providers support diarization). */
  providerAllowList?: string[]
  /** Optional placeholder shown as the first <option> when both fields are empty. */
  defaultLabel?: string
  /** Compact = side-by-side selects; default keeps that layout. */
  className?: string
  /** When true, show a "credential" row that lets the user pin a specific AIProvider row. */
  allowCredentialPick?: boolean
  disabled?: boolean
}

export default function ProviderModelPicker({
  kind,
  value,
  onChange,
  providerAllowList,
  defaultLabel,
  className,
  allowCredentialPick = false,
  disabled = false,
}: ProviderModelPickerProps) {
  const { data: aiProviders = [] } = useQuery<AIProviderRow[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders() as Promise<AIProviderRow[]>,
  })
  // STT credentials (Deepgram, Sarvam, Smallest, ElevenLabs, …) are
  // typically stored in the Integration table when the user adds them
  // via Configurations → Integrations → "Voice Platform". Pull those
  // too so the picker reflects every credential the backend can
  // actually resolve.
  const { data: integrations = [] } = useQuery<Integration[]>({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
    enabled: kind === 'stt',
  })

  const allCredentials: CredentialRow[] = [
    ...aiProviders.map<CredentialRow>((p) => ({
      id: p.id,
      provider: (p.provider || '').toLowerCase(),
      is_active: p.is_active,
      is_default: p.is_default,
      name: p.name ?? null,
      source: 'aiprovider',
    })),
    // Only merge integrations for STT — LLM credentials never live in
    // that table, so skipping it keeps the LLM picker unchanged.
    ...(kind === 'stt'
      ? integrations.map<CredentialRow>((i) => ({
          id: i.id,
          provider: (i.platform || '').toLowerCase(),
          is_active: i.is_active,
          is_default: i.is_default,
          name: i.name ?? null,
          source: 'integration',
        }))
      : []),
  ]

  const allowSet = providerAllowList
    ? new Set(providerAllowList.map((p) => p.toLowerCase()))
    : null
  const eligibleProviders = allCredentials.filter((p) => {
    if (!p.is_active) return false
    if (!allowSet) return true
    return allowSet.has(p.provider)
  })
  // Group rows by provider key so the dropdown shows one entry per
  // provider; credential pinning happens in the secondary select.
  const providerKeys = Array.from(
    new Set(eligibleProviders.map((p) => p.provider)),
  )

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', value.provider],
    queryFn: () => apiClient.getModelOptions(value.provider as string),
    enabled: !!value.provider,
  })

  const models =
    (kind === 'stt' ? modelOptions?.stt : modelOptions?.llm) || []

  // Auto-pick the first model when the provider changes and the
  // currently-selected model isn't valid for it. Avoids a confusing
  // empty-model state after the user picks a provider.
  useEffect(() => {
    if (!value.provider) return
    if (!models.length) return
    if (value.model && models.includes(value.model)) return
    onChange({ ...value, model: models[0] })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.provider, models])

  const credentialRows = value.provider
    ? allCredentials.filter(
        (p) => p.is_active && p.provider === value.provider,
      )
    : []
  const showCredentialPicker =
    allowCredentialPick && credentialRows.length > 1

  const Icon = kind === 'stt' ? AudioLines : Bot

  return (
    <div className={className ?? 'space-y-2'}>
      <div className="flex gap-3">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            <Icon className="w-3 h-3 inline mr-1" />
            {kind === 'stt' ? 'STT Provider' : 'LLM Provider'}
          </label>
          <select
            value={value.provider ?? ''}
            disabled={disabled}
            onChange={(e) => {
              const provider = e.target.value || null
              onChange({ provider, model: null, credential_id: null })
            }}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-50"
          >
            <option value="">{defaultLabel ?? 'Select a provider'}</option>
            {providerKeys.map((p) => (
              <option key={p} value={p}>
                {PROVIDER_LABELS[p] || p}
              </option>
            ))}
          </select>
          {eligibleProviders.length === 0 && (
            <p className="mt-1 text-xs text-amber-600">
              {kind === 'stt'
                ? 'No matching STT credentials configured. Add one under Configurations → Integrations.'
                : 'No matching AI providers configured for your org.'}
            </p>
          )}
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Model
          </label>
          <select
            value={value.model ?? ''}
            disabled={disabled || !value.provider}
            onChange={(e) =>
              onChange({ ...value, model: e.target.value || null })
            }
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-50 disabled:text-gray-400"
          >
            {!value.provider ? (
              <option value="">Pick a provider first</option>
            ) : models.length === 0 ? (
              <option value="">Loading models...</option>
            ) : (
              models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))
            )}
          </select>
        </div>
      </div>
      {showCredentialPicker && (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Credential
          </label>
          <select
            value={value.credential_id ?? ''}
            disabled={disabled}
            onChange={(e) =>
              onChange({
                ...value,
                credential_id: e.target.value || null,
              })
            }
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
          >
            <option value="">Org default</option>
            {credentialRows.map((c) => (
              <option key={`${c.source}:${c.id}`} value={c.id}>
                {c.name || c.id.slice(0, 8)}
                {c.is_default ? ' (default)' : ''}
                {c.source === 'integration' ? ' · Integration' : ''}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  )
}
