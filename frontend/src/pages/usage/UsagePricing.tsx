import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Card, CardBody, Spinner } from '@heroui/react'
import { Link } from 'react-router-dom'
import { ArrowLeft, DollarSign, Info, Plus, Trash2 } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { useIsAdmin } from '../../hooks/useRole'
import { useToast } from '../../hooks/useToast'
import Button from '../../components/Button'
import SearchableSelect from './SearchableSelect'
import { usageTheme } from './usageTheme'

type UsageKind = 'llm' | 'stt' | 'tts'

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

const RATE_FIELDS: Array<{ key: RateFieldKey; label: string; kinds: UsageKind[] }> = [
  { key: 'input_per_1m', label: 'Input / 1M tokens (USD)', kinds: ['llm'] },
  { key: 'output_per_1m', label: 'Output / 1M tokens (USD)', kinds: ['llm'] },
  { key: 'cache_read_per_1m', label: 'Cache read / 1M (USD)', kinds: ['llm'] },
  { key: 'cache_write_per_1m', label: 'Cache write / 1M (USD)', kinds: ['llm'] },
  { key: 'reasoning_per_1m', label: 'Reasoning / 1M (USD)', kinds: ['llm'] },
  { key: 'audio_per_minute', label: 'Audio / minute (USD)', kinds: ['llm', 'stt'] },
  { key: 'tts_per_1m_characters', label: 'TTS / 1M characters (USD)', kinds: ['tts'] },
]

const CONTROL_CLASS = `h-10 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm text-gray-900 shadow-sm outline-none transition-colors hover:border-gray-300 ${usageTheme.focusRing}`

function FormField({
  label,
  children,
  className = '',
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`min-w-0 ${className}`}>
      <span className="text-xs font-medium text-gray-500">{label}</span>
      <div className="mt-1">{children}</div>
    </div>
  )
}

function formatUsd(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  }).format(value)
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

export default function UsagePricing() {
  const isAdmin = useIsAdmin()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()

  const [model, setModel] = useState('')
  const [usageKind, setUsageKind] = useState<UsageKind>('llm')
  const [effectiveFrom, setEffectiveFrom] = useState(todayIso())
  const [rates, setRates] = useState<PricingRatesUsd>(EMPTY_RATES)

  const { data: filters } = useQuery({
    queryKey: ['org-usage', 'filters'],
    queryFn: () => apiClient.getOrgUsageFilters(),
    enabled: isAdmin,
  })

  const { data: overrides = [], isLoading } = useQuery({
    queryKey: ['usage-pricing', 'overrides'],
    queryFn: () => apiClient.listUsagePricingOverrides(),
    enabled: isAdmin,
  })

  const modelOptions = useMemo(() => {
    const fromUsage = filters?.models || []
    const fromOverrides = overrides.map((row) => row.model)
    return Array.from(new Set([...fromUsage, ...fromOverrides]))
      .sort()
      .map((name) => ({ id: name, label: name }))
  }, [filters?.models, overrides])

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
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <ToastContainer />

      <div>
        <Link
          to="/usage"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to usage
        </Link>
        <div className="mt-3 flex items-start gap-3">
          <div className="rounded-lg bg-[#fef9c3] p-2 text-[#a16207]">
            <DollarSign className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-semibold text-gray-900">Pricing overrides</h1>
              <div className="relative group">
                <button
                  type="button"
                  className="rounded-full p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                  aria-label="About pricing overrides"
                >
                  <Info className="h-4 w-4" />
                </button>
                <div
                  role="tooltip"
                  className="pointer-events-none absolute left-0 top-full z-20 mt-2 hidden w-72 rounded-lg border border-gray-200 bg-white p-3 text-xs leading-relaxed text-gray-600 shadow-lg group-hover:block group-focus-within:block"
                >
                  Set custom USD rates for this organization. Empty fields inherit the platform
                  catalog. Saving updates costs for matching usage and starts a scoped recompute.
                </div>
              </div>
            </div>
            <p className="mt-1 text-sm text-gray-500">
              Per-model rates for this org. Leave blank to use the default catalog.
            </p>
          </div>
        </div>
      </div>

      <Card className={`${usageTheme.panel} shrink-0`}>
        <CardBody className="gap-5 p-5">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Add or update override</h2>
            <p className="mt-0.5 text-xs text-gray-500">
              Saving triggers a scoped cost recompute for this model.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <SearchableSelect
              label="Model"
              placeholder="Search models…"
              value={model}
              options={modelOptions}
              onChange={setModel}
              emptyMessage="No models match"
            />
            <FormField label="Usage kind">
              <select
                className={CONTROL_CLASS}
                value={usageKind}
                onChange={(e) => {
                  setUsageKind(e.target.value as UsageKind)
                  setRates(EMPTY_RATES)
                }}
              >
                <option value="llm">LLM</option>
                <option value="stt">STT</option>
                <option value="tts">TTS</option>
              </select>
            </FormField>
            <FormField label="Effective from">
              <input
                type="date"
                className={CONTROL_CLASS}
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
              />
            </FormField>
          </div>

          <div>
            <p className="mb-3 text-xs font-medium uppercase tracking-wide text-gray-500">
              Rate overrides (USD)
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {visibleRateFields.map(({ key, label }) => (
                <FormField key={key} label={label}>
                  <input
                    type="number"
                    min={0}
                    step="any"
                    placeholder="Inherit from catalog"
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

          <div className="flex items-center justify-end gap-3 border-t border-gray-100 pt-4">
            <button
              type="button"
              className="text-sm text-gray-500 hover:text-gray-700"
              onClick={() => {
                setRates(EMPTY_RATES)
                setModel('')
              }}
            >
              Clear form
            </button>
            <Button
              variant="primary"
              leftIcon={<Plus className="h-4 w-4" />}
              disabled={!model || saveMutation.isPending}
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
            <h2 className="text-base font-semibold text-gray-900">Current overrides</h2>
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
                        {formatUsd(row.rates.input_per_1m)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {formatUsd(row.rates.output_per_1m)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {formatUsd(row.rates.audio_per_minute)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">
                        {formatUsd(row.rates.tts_per_1m_characters)}
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
