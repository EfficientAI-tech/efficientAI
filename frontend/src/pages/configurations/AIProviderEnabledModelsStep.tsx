import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, Search, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import type { ModelProvider } from '../../types/api'
import { usageTheme } from '../usage/usageTheme'

type ModelOptions = {
  llm?: string[]
  stt?: string[]
  tts?: string[]
  s2s?: string[]
}

type SectionKey = 'llm' | 'stt' | 'tts' | 's2s'

const SECTIONS: Array<{ key: SectionKey; label: string }> = [
  { key: 'llm', label: 'LLM' },
  { key: 'stt', label: 'STT' },
  { key: 'tts', label: 'TTS' },
  { key: 's2s', label: 'Speech-to-speech' },
]

type Props = {
  provider: ModelProvider
  enabledModels: string[]
  onChange: (models: string[]) => void
  gatewayModel?: string
}

/** Every whitespace-separated term must appear (case-insensitive), so "gpt 4o" matches "gpt-4o-mini". */
function matchesQuery(model: string, terms: string[]) {
  const haystack = model.toLowerCase()
  return terms.every((term) => haystack.includes(term))
}

function ModelChip({
  model,
  selected,
  onToggle,
}: {
  model: string
  selected: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      title={model}
      className={`flex w-full items-center gap-2 rounded-xl border px-3 py-2.5 text-left transition-all ${
        selected
          ? `${usageTheme.pillActive} ring-1 ring-[#facc15]/40`
          : 'border-gray-200 bg-white text-gray-800 hover:border-[#fde047] hover:bg-[#fefce8]/60'
      }`}
    >
      <span
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-colors ${
          selected
            ? 'border-[#ca8a04] bg-[#facc15] text-[#422006]'
            : 'border-gray-300 bg-white text-transparent'
        }`}
      >
        <Check className="h-3 w-3" strokeWidth={3} />
      </span>
      <span className="min-w-0 flex-1 text-sm leading-snug text-gray-900 break-all">{model}</span>
    </button>
  )
}

export default function AIProviderEnabledModelsStep({
  provider,
  enabledModels,
  onChange,
  gatewayModel,
}: Props) {
  const [customModel, setCustomModel] = useState('')
  const [query, setQuery] = useState('')

  useEffect(() => {
    setQuery('')
  }, [provider])

  const searchTerms = useMemo(
    () => query.trim().toLowerCase().split(/\s+/).filter(Boolean),
    [query],
  )
  const isSearching = searchTerms.length > 0
  const filterModels = (models: string[]) =>
    isSearching ? models.filter((model) => matchesQuery(model, searchTerms)) : models

  const { data: options, isLoading } = useQuery({
    queryKey: ['model-options', provider],
    queryFn: () => apiClient.getModelOptions(provider),
    enabled: Boolean(provider),
  })

  const catalog = useMemo(() => (options || {}) as ModelOptions, [options])
  const selected = useMemo(() => new Set(enabledModels), [enabledModels])

  const catalogModelSet = useMemo(() => {
    const models = new Set<string>()
    for (const { key } of SECTIONS) {
      for (const model of catalog[key] || []) {
        models.add(model)
      }
    }
    return models
  }, [catalog])

  const catalogIsEmpty = useMemo(
    () => SECTIONS.every(({ key }) => (catalog[key] || []).length === 0),
    [catalog],
  )

  const providerKey = String(provider).toLowerCase()
  const isCustomProvider = providerKey === 'custom'
  const isOpenRouterProvider = providerKey === 'openrouter'
  const showManualAdd =
    isCustomProvider || isOpenRouterProvider || (!isLoading && catalogIsEmpty)

  const customModels = useMemo(
    () => enabledModels.filter((model) => !catalogModelSet.has(model)),
    [enabledModels, catalogModelSet],
  )

  const toggle = (model: string) => {
    const next = new Set(enabledModels)
    if (next.has(model)) next.delete(model)
    else next.add(model)
    onChange(Array.from(next).sort())
  }

  // While searching, All / Clear apply only to the visible matches.
  const selectSection = (key: SectionKey) => {
    const models = filterModels(catalog[key] || [])
    const next = new Set(enabledModels)
    models.forEach((m) => next.add(m))
    onChange(Array.from(next).sort())
  }

  const clearSection = (key: SectionKey) => {
    const models = new Set(filterModels(catalog[key] || []))
    onChange(enabledModels.filter((m) => !models.has(m)))
  }

  const addModel = (raw: string) => {
    const name = raw.trim()
    if (!name) return
    if (!selected.has(name)) {
      onChange([...enabledModels, name].sort())
    }
  }

  const addCustomModel = () => {
    addModel(customModel)
    setCustomModel('')
  }

  const hasAnyModels = !catalogIsEmpty || customModels.length > 0
  const visibleCustomModels = filterModels(customModels)
  const totalMatches =
    SECTIONS.reduce((sum, { key }) => sum + filterModels(catalog[key] || []).length, 0) +
    visibleCustomModels.length

  const gateway = gatewayModel?.trim()

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[#fde047]/50 bg-[#fefce8]/40 px-3 py-2.5">
        <p className="text-sm text-gray-800">
          Tap models to allow this integration to use them in evals, agents, and pricing.
        </p>
        <p className="mt-1 text-xs text-gray-600">
          Leave all off to allow the full provider catalog.
        </p>
      </div>

      {gateway ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
          Gateway model <span className="font-medium break-all">{gateway}</span> stays available
          when configured.
        </div>
      ) : null}

      {isCustomProvider && !gateway && enabledModels.length === 0 && !isLoading ? (
        <div className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700">
          Add custom model IDs below, or set a <span className="font-medium">Gateway model</span> on
          the previous step for a single pinned gateway model.
        </div>
      ) : null}

      {!isLoading && hasAnyModels ? (
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setQuery('')
            }}
            placeholder="Search models…"
            aria-label="Search models"
            className={`w-full rounded-lg border border-gray-200 py-2 pl-9 pr-9 text-sm focus:outline-none ${usageTheme.focusRing}`}
          />
          {query ? (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-gray-400 hover:text-gray-700"
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      ) : null}

      {!isLoading && isSearching && totalMatches === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm text-gray-700">
          No models match <span className="font-medium break-all">“{query.trim()}”</span>.
          {showManualAdd ? (
            <button
              type="button"
              onClick={() => addModel(query)}
              className="ml-2 font-medium text-[#a16207] underline-offset-2 hover:underline"
            >
              Add it as a model ID
            </button>
          ) : null}
        </div>
      ) : null}

      {isLoading ? (
        <p className="text-sm text-gray-500">Loading catalog models…</p>
      ) : (
        SECTIONS.map(({ key, label }) => {
          const allModels = catalog[key] || []
          const models = filterModels(allModels)
          if (models.length === 0) return null
          const sectionSelected = allModels.filter((m) => selected.has(m)).length
          return (
            <div key={key} className={`${usageTheme.panel} overflow-hidden`}>
              <div className={`flex items-center justify-between gap-2 px-3 py-2 ${usageTheme.panelHeader}`}>
                <div>
                  <span className="text-sm font-semibold text-gray-900">{label}</span>
                  <span className="ml-2 text-xs text-gray-500">
                    {sectionSelected}/{allModels.length} selected
                    {isSearching ? ` · ${models.length} match${models.length === 1 ? '' : 'es'}` : ''}
                  </span>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium ${usageTheme.pillInactive}`}
                    onClick={() => selectSection(key)}
                  >
                    {isSearching ? 'All matches' : 'All'}
                  </button>
                  <button
                    type="button"
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium ${usageTheme.pillMuted}`}
                    onClick={() => clearSection(key)}
                  >
                    {isSearching ? 'Clear matches' : 'Clear'}
                  </button>
                </div>
              </div>
              <div className="grid max-h-52 grid-cols-1 gap-2 overflow-y-auto p-3 sm:grid-cols-2">
                {models.map((model) => (
                  <ModelChip
                    key={model}
                    model={model}
                    selected={selected.has(model)}
                    onToggle={() => toggle(model)}
                  />
                ))}
              </div>
            </div>
          )
        })
      )}

      {visibleCustomModels.length > 0 ? (
        <div className={`${usageTheme.panel} overflow-hidden`}>
          <div className={`px-3 py-2 ${usageTheme.panelHeader}`}>
            <span className="text-sm font-semibold text-gray-900">Enabled models</span>
            <span className="ml-2 text-xs text-gray-500">
              {customModels.filter((m) => selected.has(m)).length}/{customModels.length} selected
            </span>
          </div>
          <div className="grid max-h-52 grid-cols-1 gap-2 overflow-y-auto p-3 sm:grid-cols-2">
            {visibleCustomModels.map((model) => (
              <ModelChip
                key={model}
                model={model}
                selected={selected.has(model)}
                onToggle={() => toggle(model)}
              />
            ))}
          </div>
        </div>
      ) : null}

      {showManualAdd ? (
        <div className={`${usageTheme.panel} p-3`}>
          <label className="block text-sm font-medium text-gray-900 mb-2">
            {isCustomProvider
              ? 'Custom model ID'
              : isOpenRouterProvider
                ? 'OpenRouter model ID'
                : 'Add deployment / model name'}
          </label>
          {isOpenRouterProvider ? (
            <p className="mb-2 text-xs text-gray-600">
              Use OpenRouter slugs like <span className="font-medium">vendor/model</span> (for
              example <span className="font-medium">anthropic/claude-sonnet-4</span>).
            </p>
          ) : null}
          <div className="flex gap-2">
            <input
              type="text"
              value={customModel}
              onChange={(e) => setCustomModel(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  addCustomModel()
                }
              }}
              className={`flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none ${usageTheme.focusRing}`}
              placeholder={
                isCustomProvider
                  ? 'e.g. openai/gpt-4o or production-gpt4'
                  : isOpenRouterProvider
                    ? 'e.g. openai/gpt-4o'
                    : 'e.g. accounts/fireworks/models/gpt-oss-120b'
              }
            />
            <button type="button" onClick={addCustomModel} className={usageTheme.applyBtn}>
              Add
            </button>
          </div>
        </div>
      ) : null}

      <p className="text-xs text-gray-500">
        {enabledModels.length > 0
          ? `${enabledModels.length} model${enabledModels.length === 1 ? '' : 's'} enabled`
          : isCustomProvider
            ? 'No models enabled yet — add model IDs above or set a gateway model on step 1'
            : 'No restriction — full catalog allowed'}
      </p>
    </div>
  )
}
