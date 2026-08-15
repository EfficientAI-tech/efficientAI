import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Card, CardBody, Spinner } from '@heroui/react'
import { Plus, Trash2, Info } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { useIsAdmin } from '../../hooks/useRole'
import { useToast } from '../../hooks/useToast'
import Button from '../../components/Button'
import SearchableSelect from './SearchableSelect'
import ProviderCredentialSelect from './ProviderCredentialSelect'
import { usageTheme } from './usageTheme'
import {
  buildPricingModelOptions,
  credentialDisplayLabel,
  type PricingUsageKind,
} from './pricingModelOptions'
import type { AIProvider } from '../../types/api'

type UsageKind = PricingUsageKind

type PricingRatesUsd = {
  input_per_1m?: number | null
  output_per_1m?: number | null
  cache_read_per_1m?: number | null
  cache_write_per_1m?: number | null
  reasoning_per_1m?: number | null
  audio_per_minute?: number | null
  tts_per_1m_characters?: number | null
}

type PricingOverride = {
  id: string
  model: string
  usage_kind: string
  effective_from: string
  effective_to?: string | null
  rates: PricingRatesUsd
  recompute_enqueued?: boolean
  recompute_job_id?: string | null
}

type RateFieldKey = keyof PricingRatesUsd

const EMPTY_RATES: PricingRatesUsd = {
  input_per_1m: undefined,
  output_per_1m: undefined,
  cache_read_per_1m: undefined,
  cache_write_per_1m: undefined,
  reasoning_per_1m: undefined,
  audio_per_minute: undefined,
  tts_per_1m_characters: undefined,
}

const RATE_FIELDS: Array<{
  key: RateFieldKey
  label: string
  kinds: UsageKind[]
  hint: string
}> = [
  {
    key: 'input_per_1m',
    label: 'Input / 1M tokens ($)',
    kinds: ['llm'],
    hint: 'USD per 1 million prompt or input tokens. Used when costing LLM calls for this model.',
  },
  {
    key: 'output_per_1m',
    label: 'Output / 1M tokens ($)',
    kinds: ['llm'],
    hint: 'USD per 1 million completion or output tokens returned by the model.',
  },
  {
    key: 'cache_read_per_1m',
    label: 'Cache read / 1M ($)',
    kinds: ['llm'],
    hint: 'USD per 1 million tokens read from prompt cache, when the provider bills cached input separately.',
  },
  {
    key: 'cache_write_per_1m',
    label: 'Cache write / 1M ($)',
    kinds: ['llm'],
    hint: 'USD per 1 million tokens written to prompt cache on the first request.',
  },
  {
    key: 'reasoning_per_1m',
    label: 'Reasoning / 1M ($)',
    kinds: ['llm'],
    hint: 'USD per 1 million reasoning or thinking tokens (e.g. o-series models).',
  },
  {
    key: 'audio_per_minute',
    label: 'Audio / minute ($)',
    kinds: ['llm', 'stt'],
    hint: 'USD per minute of audio processed — STT transcription or multimodal audio input on LLM calls.',
  },
  {
    key: 'tts_per_1m_characters',
    label: 'TTS / 1M characters ($)',
    kinds: ['tts'],
    hint: 'USD per 1 million characters sent to the TTS model for synthesis.',
  },
]

const FIELD_HINTS = {
  provider:
    'AI company from Integrations (e.g. OpenAI, Anthropic). Pick the credential whose models you want to price.',
  model:
    'Model name for the selected provider and usage kind. Only enabled models for that integration are listed.',
  usageKind:
    'Choose LLM, STT, or TTS first — this filters which models appear. Rate fields below match the kind.',
  effectiveFrom:
    'First calendar day this override applies. Saving recalculates historical usage for this model from this date.',
  ratesSection:
    'Enter USD rates only. Leave a field empty to inherit the platform catalog. At least one rate is required to save.',
} as const

const CONTROL_CLASS = `h-10 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm text-gray-900 shadow-sm outline-none transition-colors hover:border-gray-300 ${usageTheme.focusRing}`

function FieldHint({ title, children }: { title: string; children: ReactNode }) {
  return (
    <span className="relative inline-flex group">
      <Info
        className="h-3.5 w-3.5 cursor-help text-gray-400 hover:text-gray-600"
        aria-label={title}
      />
      <span
        role="tooltip"
        className="pointer-events-none absolute left-0 top-full z-30 mt-1.5 hidden w-64 rounded-lg border border-gray-200 bg-white p-2.5 text-xs font-normal leading-relaxed text-gray-600 shadow-lg group-hover:block group-focus-within:block"
      >
        <span className="block text-[11px] font-semibold uppercase tracking-wide text-gray-900">
          {title}
        </span>
        <span className="mt-1 block">{children}</span>
      </span>
    </span>
  )
}

function FormField({
  label,
  hint,
  children,
  className = '',
}: {
  label: string
  hint?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`min-w-0 ${className}`}>
      <div className="flex items-center gap-1.5">
        <span className="text-xs font-medium text-gray-500">{label}</span>
        {hint ? (
          <FieldHint title={label}>{hint}</FieldHint>
        ) : null}
      </div>
      <div className="mt-1">{children}</div>
    </div>
  )
}


function formatRateUsd(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `$${value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}`
}

function ratesFromApi(raw?: Record<string, number | null> | null): PricingRatesUsd {
  if (!raw) return { ...EMPTY_RATES }
  return {
    input_per_1m: raw.input_per_1m ?? undefined,
    output_per_1m: raw.output_per_1m ?? undefined,
    cache_read_per_1m: raw.cache_read_per_1m ?? undefined,
    cache_write_per_1m: raw.cache_write_per_1m ?? undefined,
    reasoning_per_1m: raw.reasoning_per_1m ?? undefined,
    audio_per_minute: raw.audio_per_minute ?? undefined,
    tts_per_1m_characters: raw.tts_per_1m_characters ?? undefined,
  }
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

export default function UsagePricing() {
  const isAdmin = useIsAdmin()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()

  const [credentialId, setCredentialId] = useState('')
  const [model, setModel] = useState('')
  const [usageKind, setUsageKind] = useState<UsageKind>('llm')
  const [effectiveFrom, setEffectiveFrom] = useState(todayIso())
  const [rates, setRates] = useState<PricingRatesUsd>(EMPTY_RATES)
  const [ratePrefillSource, setRatePrefillSource] = useState<'catalog' | 'override' | null>(null)
  const selectionRef = useRef({ model: '', usageKind: '' as UsageKind })

  const { data: aiProviders = [] } = useQuery({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
    enabled: isAdmin,
  })

  const activeCredentials = useMemo(
    () =>
      (aiProviders as AIProvider[])
        .filter((row) => row.is_active)
        .sort((a, b) => credentialDisplayLabel(a).localeCompare(credentialDisplayLabel(b))),
    [aiProviders],
  )

  const selectedCredential = useMemo(
    () => activeCredentials.find((row) => row.id === credentialId),
    [activeCredentials, credentialId],
  )

  const { data: providerCatalog } = useQuery({
    queryKey: ['model-options', selectedCredential?.provider],
    queryFn: () => apiClient.getModelOptions(selectedCredential!.provider),
    enabled: Boolean(selectedCredential?.provider),
  })

  const { data: availableModels = [] } = useQuery({
    queryKey: ['usage-pricing', 'available-models'],
    queryFn: async () => {
      const payload = await apiClient.listUsagePricingAvailableModels()
      return payload.models || []
    },
    enabled: isAdmin,
  })

  const { data: overrides = [], isLoading } = useQuery({
    queryKey: ['usage-pricing', 'overrides'],
    queryFn: () => apiClient.listUsagePricingOverrides(),
    enabled: isAdmin,
  })

  const { data: effectivePricing, isFetching: effectiveLoading } = useQuery({
    queryKey: ['usage-pricing', 'effective', model, usageKind, effectiveFrom],
    queryFn: () =>
      apiClient.getUsagePricingEffective(model, {
        usage_kind: usageKind,
        as_of: effectiveFrom,
      }),
    enabled: isAdmin && Boolean(model),
  })

  const eligibleModelSet = useMemo(
    () => new Set(availableModels || []),
    [availableModels],
  )

  const modelOptions = useMemo(
    () =>
      buildPricingModelOptions({
        credential: selectedCredential,
        catalog: providerCatalog,
        kind: usageKind,
        eligibleModels: eligibleModelSet,
        overrideModels: overrides
          .filter((row) => row.usage_kind === usageKind)
          .map((row) => row.model),
      }),
    [selectedCredential, providerCatalog, usageKind, eligibleModelSet, overrides],
  )

  const resetModelAndRates = () => {
    setModel('')
    setRates(EMPTY_RATES)
    setRatePrefillSource(null)
    selectionRef.current = { model: '', usageKind: 'llm' }
  }

  useEffect(() => {
    if (credentialId || activeCredentials.length !== 1) return
    setCredentialId(activeCredentials[0].id)
  }, [activeCredentials, credentialId])

  useEffect(() => {
    if (!model) {
      setRates(EMPTY_RATES)
      setRatePrefillSource(null)
      selectionRef.current = { model: '', usageKind: usageKind }
      return
    }
    if (!effectivePricing) return

    const selectionChanged =
      selectionRef.current.model !== model ||
      selectionRef.current.usageKind !== usageKind

    const nextRates = ratesFromApi(effectivePricing.effective_rates)
    setRates(nextRates)
    setRatePrefillSource(
      effectivePricing.has_override
        ? 'override'
        : effectivePricing.effective_rates
          ? 'catalog'
          : null,
    )

    if (selectionChanged && effectivePricing.override?.effective_from) {
      setEffectiveFrom(effectivePricing.override.effective_from)
    }

    selectionRef.current = { model, usageKind }
  }, [model, usageKind, effectivePricing])

  const handleCredentialChange = (nextId: string) => {
    setCredentialId(nextId)
    resetModelAndRates()
  }

  const handleUsageKindChange = (nextKind: UsageKind) => {
    setUsageKind(nextKind)
    resetModelAndRates()
  }

  const visibleRateFields = useMemo(
    () => RATE_FIELDS.filter((field) => field.kinds.includes(usageKind)),
    [usageKind]
  )

  const saveMutation = useMutation({
    mutationFn: () => {
      const payloadRates = Object.fromEntries(
        Object.entries(rates).filter((entry): entry is [string, number] => {
          const value = entry[1]
          return value != null && !Number.isNaN(value)
        })
      )
      return apiClient.upsertUsagePricingOverride(model, {
        usage_kind: usageKind,
        effective_from: effectiveFrom,
        rates: payloadRates,
        recompute: true,
      })
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['usage-pricing'] })
      queryClient.invalidateQueries({ queryKey: ['org-usage'] })
      setRates(EMPTY_RATES)
      setRatePrefillSource(null)
      showToast(
        data.recompute_enqueued
          ? 'Override saved; cost recompute started'
          : 'Override saved (recompute already running)',
        'success'
      )
    },
    onError: (error: any) => {
      showToast(error.response?.data?.detail || 'Failed to save override', 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (row: PricingOverride) =>
      apiClient.deleteUsagePricingOverride(row.model, {
        usage_kind: row.usage_kind,
        effective_from: row.effective_from,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['usage-pricing'] })
      queryClient.invalidateQueries({ queryKey: ['org-usage'] })
      showToast('Override removed', 'success')
    },
    onError: (error: any) => {
      showToast(error.response?.data?.detail || 'Failed to delete override', 'error')
    },
  })

  if (!isAdmin) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-600">
        Organization admin access is required to manage pricing overrides.
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <ToastContainer />

      <Card className={`${usageTheme.panel} shrink-0`}>
        <CardBody className="gap-5 overflow-visible p-5">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Add or update override</h2>
            <p className="mt-0.5 text-xs text-gray-500">
              Per-model rates for this org. Leave blank to use the default catalog. Saving triggers
              a scoped cost recompute.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <ProviderCredentialSelect
              label="Provider"
              hint={FIELD_HINTS.provider}
              value={credentialId}
              credentials={activeCredentials}
              onChange={handleCredentialChange}
              placeholder="Select integration…"
            />
            <FormField label="Usage kind" hint={FIELD_HINTS.usageKind}>
              <select
                className={CONTROL_CLASS}
                value={usageKind}
                disabled={!credentialId}
                onChange={(e) => handleUsageKindChange(e.target.value as UsageKind)}
              >
                <option value="llm">LLM</option>
                <option value="stt">STT</option>
                <option value="tts">TTS</option>
              </select>
            </FormField>
            <SearchableSelect
              label="Model"
              hint={FIELD_HINTS.model}
              placeholder={
                credentialId
                  ? 'Search models for this provider…'
                  : 'Select a provider first'
              }
              value={model}
              options={modelOptions}
              onChange={setModel}
              disabled={!credentialId}
              emptyMessage={
                credentialId
                  ? `No ${usageKind.toUpperCase()} models for this integration — enable them in Integrations`
                  : 'Select a provider first'
              }
            />
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <FormField label="Effective from" hint={FIELD_HINTS.effectiveFrom}>
              <input
                type="date"
                className={CONTROL_CLASS}
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
              />
            </FormField>
          </div>

          {credentialId && modelOptions.length === 0 ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              No {usageKind.toUpperCase()} models are available for this integration. Enable models
              in Integrations → AI provider → step 2, or pick another usage kind.
            </p>
          ) : null}

          {activeCredentials.length === 0 ? (
            <p className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
              Add an AI provider in Integrations before setting pricing overrides.
            </p>
          ) : null}

          {model ? (
          <div>
            {effectiveLoading ? (
              <div className="mb-3 flex items-center gap-2 text-xs text-gray-500">
                <Spinner size="sm" />
                Loading current rates…
              </div>
            ) : ratePrefillSource ? (
              <p
                className={`mb-3 rounded-lg px-3 py-2 text-xs ${
                  ratePrefillSource === 'override'
                    ? 'border border-[#fde047]/60 bg-[#fefce8] text-[#854d0e]'
                    : 'border border-gray-200 bg-gray-50 text-gray-600'
                }`}
              >
                {ratePrefillSource === 'override'
                  ? 'Prefilled from your org override — these are the rates usage is billed at today. Edit and save to update.'
                  : 'Prefilled from platform catalog — these are the default rates in effect. Edit and save to create an org override.'}
              </p>
            ) : (
              <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                No catalog rate found for this model on the selected date. Enter rates manually.
              </p>
            )}
            <div className="mb-3 flex items-center gap-1.5">
              <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
                Rate overrides ($)
              </p>
              <FieldHint title="Rate overrides">{FIELD_HINTS.ratesSection}</FieldHint>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {visibleRateFields.map(({ key, label, hint }) => (
                <FormField key={key} label={label} hint={hint}>
                  <input
                    type="number"
                    min={0}
                    step="any"
                    className={CONTROL_CLASS}
                    value={rates[key] != null ? String(rates[key]) : ''}
                    onChange={(e) => {
                      const value = e.target.value
                      setRates((prev) => ({
                        ...prev,
                        [key]: value === '' ? undefined : Number(value),
                      }))
                    }}
                  />
                </FormField>
              ))}
            </div>
          </div>
          ) : (
            <p className="text-xs text-gray-500">
              Select a provider, usage kind, and model to configure rate overrides.
            </p>
          )}

          <div className="flex items-center justify-end gap-3 border-t border-gray-100 pt-4">
            <button
              type="button"
              className="text-sm text-gray-500 hover:text-gray-700"
              onClick={() => {
                setRates(EMPTY_RATES)
                setModel('')
                setCredentialId('')
              }}
            >
              Clear form
            </button>
            <Button
              variant="primary"
              leftIcon={<Plus className="h-4 w-4" />}
              disabled={!credentialId || !model || saveMutation.isPending}
              isLoading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              Save override
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card className={`${usageTheme.panel} min-h-0`}>
        <CardBody className="flex min-h-0 flex-col gap-3 p-5">
          <div className="flex shrink-0 items-center justify-between gap-2">
            <div className="flex items-center gap-1.5">
              <h2 className="text-base font-semibold text-gray-900">Current overrides</h2>
              <FieldHint title="Current overrides">
                Active org-specific rates in USD. Delete a row to fall back to the platform catalog
                for that model.
              </FieldHint>
            </div>
            {!isLoading ? (
              <span className="text-xs text-gray-500">{overrides.length} total</span>
            ) : null}
          </div>

          {isLoading ? (
            <div className="flex justify-center py-12">
              <Spinner />
            </div>
          ) : overrides.length === 0 ? (
            <p className="py-10 text-center text-sm text-gray-500">
              No overrides yet. Platform catalog rates apply to all usage.
            </p>
          ) : (
            <div className="max-h-[min(55vh,28rem)] overflow-auto rounded-lg border border-gray-200">
              <table className="min-w-full text-sm">
                <thead className="sticky top-0 z-10 bg-gray-50 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                  <tr className="border-b border-gray-200">
                    <th className="px-4 py-2.5">Model</th>
                    <th className="px-4 py-2.5">Kind</th>
                    <th className="px-4 py-2.5">Effective</th>
                    <th className="px-4 py-2.5 text-right">Input</th>
                    <th className="px-4 py-2.5 text-right">Output</th>
                    <th className="px-4 py-2.5 text-right">Audio</th>
                    <th className="px-4 py-2.5 text-right">TTS</th>
                    <th className="px-4 py-2.5 w-12" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {overrides.map((row) => (
                    <tr key={row.id} className="hover:bg-gray-50/80">
                      <td className="whitespace-nowrap px-4 py-2.5 font-medium text-gray-900">
                        {row.model}
                      </td>
                      <td className="px-4 py-2.5 uppercase text-gray-600">{row.usage_kind}</td>
                      <td className="whitespace-nowrap px-4 py-2.5 text-gray-600">
                        {row.effective_from}
                        {row.effective_to ? ` → ${row.effective_to}` : ''}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {formatRateUsd(row.rates.input_per_1m)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {formatRateUsd(row.rates.output_per_1m)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {formatRateUsd(row.rates.audio_per_minute)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {formatRateUsd(row.rates.tts_per_1m_characters)}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <button
                          type="button"
                          className="rounded p-1 text-red-600 hover:bg-red-50 hover:text-red-800"
                          onClick={() => deleteMutation.mutate(row)}
                          disabled={deleteMutation.isPending}
                          aria-label={`Delete override for ${row.model}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
