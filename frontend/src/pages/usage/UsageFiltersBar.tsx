import { useMemo, useState } from 'react'
import { Chip } from '@heroui/react'
import { ChevronDown, Filter, SlidersHorizontal } from 'lucide-react'
import SearchableSelect from './SearchableSelect'
import UsageDateRangePicker from './UsageDateRangePicker'
import { usageTheme } from './usageTheme'
import { CALL_IMPORT_PRODUCT_SECTIONS, USAGE_SECTION_SOURCE_PREFIX } from './usageProductHints'

type Kind = '' | 'llm' | 'stt' | 'tts'

type FilterOptions = {
  workspaces: Array<{ id: string; name: string }>
  call_imports: Array<{ id: string; label: string }>
  evaluations: Array<{ id: string; label: string }>
  resources?: Array<{ id: string; label: string; type?: string; product_section?: string }>
  product_sections?: Array<{ id: string; label: string }>
  models: string[]
  usage_kinds: Array<{ id: string; label: string }>
  datasets?: string[]
  tags?: Array<{ id: string; label: string }>
}

type ActiveChip = { key: string; label: string; onClear: () => void }

type UsageFiltersBarProps = {
  start: string
  end: string
  workspaceId: string
  callImportId: string
  evaluationId: string
  dataset: string
  tagId: string
  usageKind: Kind
  model: string
  productSection?: string
  options?: FilterOptions
  filtersLoading?: boolean
  onDateApply: (start: string, end: string) => void
  onWorkspaceChange: (id: string) => void
  onCallImportChange: (id: string) => void
  onDatasetChange: (value: string) => void
  onTagChange: (value: string) => void
  onEvaluationChange: (id: string) => void
  onUsageKindChange: (v: Kind) => void
  onModelChange: (v: string) => void
  onClearAll: () => void
}

const KIND_OPTIONS: Array<{ id: Kind; label: string }> = [
  { id: '', label: 'All' },
  { id: 'llm', label: 'LLM' },
  { id: 'stt', label: 'STT' },
  { id: 'tts', label: 'TTS' },
]

export default function UsageFiltersBar({
  start,
  end,
  workspaceId,
  callImportId,
  evaluationId,
  dataset,
  tagId,
  usageKind,
  model,
  productSection = '',
  options,
  filtersLoading,
  onDateApply,
  onWorkspaceChange,
  onCallImportChange,
  onDatasetChange,
  onTagChange,
  onEvaluationChange,
  onUsageKindChange,
  onModelChange,
  onClearAll,
}: UsageFiltersBarProps) {
  const [expanded, setExpanded] = useState(false)

  const workspaces = options?.workspaces ?? []
  const callImports = options?.call_imports ?? []
  const evaluations = options?.evaluations ?? []
  const resources = options?.resources ?? []
  const datasets = options?.datasets ?? []
  const tags = options?.tags ?? []
  const models = options?.models ?? []
  const availableKinds = useMemo(
    () => new Set(options?.usage_kinds?.map((k) => k.id) ?? []),
    [options?.usage_kinds],
  )

  const sectionSourceOptions = useMemo(() => {
    if (callImportId) return []
    return (options?.product_sections ?? [])
      .filter((s) => !CALL_IMPORT_PRODUCT_SECTIONS.has(s.id))
      .map((s) => ({
        id: `${USAGE_SECTION_SOURCE_PREFIX}${s.id}`,
        label: s.label,
      }))
  }, [callImportId, options?.product_sections])

  const sourceOptions = callImportId ? evaluations : [...sectionSourceOptions, ...resources]
  const sourceSelectValue =
    evaluationId ||
    (productSection ? `${USAGE_SECTION_SOURCE_PREFIX}${productSection}` : '')

  const activeChips = useMemo((): ActiveChip[] => {
    const chips: ActiveChip[] = []
    const wsLabel = workspaces.find((w) => w.id === workspaceId)?.name
    if (workspaceId && wsLabel) {
      chips.push({
        key: 'workspace',
        label: wsLabel,
        onClear: () => onWorkspaceChange(''),
      })
    }
    const importLabel = callImports.find((c) => c.id === callImportId)?.label
    if (callImportId && importLabel) {
      chips.push({
        key: 'call_import',
        label: importLabel,
        onClear: () => onCallImportChange(''),
      })
    }
    if (dataset) {
      chips.push({
        key: 'dataset',
        label: dataset,
        onClear: () => onDatasetChange(''),
      })
    }
    if (tagId) {
      const tagLabel = tags.find((t) => t.id === tagId)?.label
      if (tagLabel) {
        chips.push({
          key: 'tag',
          label: tagLabel,
          onClear: () => onTagChange(''),
        })
      }
    }
    const sourceLabel =
      sourceOptions.find((e) => e.id === sourceSelectValue)?.label ||
      evaluations.find((e) => e.id === evaluationId)?.label ||
      resources.find((r) => r.id === evaluationId)?.label
    if ((evaluationId || productSection) && sourceLabel) {
      chips.push({
        key: 'evaluation',
        label: sourceLabel,
        onClear: () => onEvaluationChange(''),
      })
    }
    if (usageKind) {
      chips.push({
        key: 'kind',
        label: usageKind.toUpperCase(),
        onClear: () => onUsageKindChange(''),
      })
    }
    if (model) {
      chips.push({
        key: 'model',
        label: model,
        onClear: () => onModelChange(''),
      })
    }
    return chips
  }, [
    workspaceId,
    workspaces,
    callImportId,
    callImports,
    dataset,
    tagId,
    tags,
    evaluationId,
    productSection,
    sourceSelectValue,
    sourceOptions,
    evaluations,
    resources,
    usageKind,
    model,
    onWorkspaceChange,
    onCallImportChange,
    onDatasetChange,
    onTagChange,
    onEvaluationChange,
    onUsageKindChange,
    onModelChange,
  ])

  const hasScopeFilters = activeChips.length > 0

  const kindHint = (kind: Kind): string | undefined => {
    if (!kind) return undefined
    if (availableKinds.has(kind)) return undefined
    return `No ${kind.toUpperCase()} usage in this date range`
  }

  return (
    <div className={usageTheme.panel}>
      <div className={`flex flex-wrap items-center gap-2 px-3 py-2 ${usageTheme.panelHeader}`}>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-sm font-semibold text-gray-800 hover:bg-[#fef9c3]/60 ${usageTheme.linkStrong}`}
        >
          <SlidersHorizontal className="h-4 w-4 text-primary-600" />
          {expanded ? 'Hide filters' : 'More filters'}
          <ChevronDown
            className={`h-4 w-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </button>

        <div className="h-5 w-px bg-[#fde047]/60 hidden sm:block" />

        <UsageDateRangePicker start={start} end={end} onApply={onDateApply} />

        {filtersLoading ? (
          <span className="text-xs text-gray-400 ml-1">Updating options…</span>
        ) : null}

        {hasScopeFilters ? (
          <button
            type="button"
            onClick={onClearAll}
            className={`ml-auto text-xs ${usageTheme.linkStrong}`}
          >
            Clear scope
          </button>
        ) : null}
      </div>

      {!expanded && hasScopeFilters ? (
        <div className="flex flex-wrap gap-1.5 px-3 py-2 border-t border-[#fde047]/30">
          {activeChips.map((chip) => (
            <Chip
              key={chip.key}
              size="sm"
              variant="flat"
              onClose={chip.onClear}
              classNames={{
                base: usageTheme.chipBase,
                content: `${usageTheme.chipContent} text-xs max-w-[14rem] truncate`,
              }}
            >
              {chip.label}
            </Chip>
          ))}
        </div>
      ) : null}

      {expanded ? (
        <div className="space-y-3 border-t border-[#fde047]/30 p-3">
          <p className="text-xs text-gray-500 flex items-center gap-1.5">
            <Filter className="h-3.5 w-3.5 text-primary-600" />
            Jump to a level or click rows in the table to drill down.
          </p>

          <div className="grid gap-3 md:grid-cols-3">
            <SearchableSelect
              label="Workspace"
              placeholder="All workspaces"
              value={workspaceId}
              options={workspaces.map((w) => ({ id: w.id, label: w.name }))}
              onChange={onWorkspaceChange}
              emptyMessage="No workspace usage in this date range"
            />
            <SearchableSelect
              label="Dataset"
              placeholder="All datasets"
              value={dataset}
              options={datasets.map((d) => ({ id: d, label: d }))}
              onChange={onDatasetChange}
              emptyMessage="No datasets in this workspace"
              disabled={datasets.length === 0}
            />
            <SearchableSelect
              label="Tag"
              placeholder="All tags"
              value={tagId}
              options={tags}
              onChange={onTagChange}
              emptyMessage="No tags defined"
              disabled={tags.length === 0}
            />
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <SearchableSelect
              label="Call import batch"
              placeholder="All call import batches"
              value={callImportId}
              options={callImports}
              onChange={onCallImportChange}
              emptyMessage="No imports with usage in this range"
              disabled={callImports.length === 0}
            />
            <SearchableSelect
              label={callImportId ? 'Evaluation run' : 'Source'}
              placeholder={
                callImportId
                  ? 'All evaluations for import'
                  : 'Agents, voice sims, telephony, …'
              }
              value={sourceSelectValue}
              options={sourceOptions}
              onChange={onEvaluationChange}
              emptyMessage="No matching usage in this range"
              disabled={sourceOptions.length === 0}
            />
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-gray-500 shrink-0">Kind</span>
              {KIND_OPTIONS.map((k) => {
                const disabled = k.id !== '' && !availableKinds.has(k.id)
                const hint = kindHint(k.id)
                return (
                  <button
                    key={k.id || 'all'}
                    type="button"
                    disabled={disabled}
                    title={hint}
                    onClick={() => !disabled && onUsageKindChange(k.id)}
                    className={`rounded-full px-3 py-1 text-xs font-medium transition-colors border ${
                      usageKind === k.id && !disabled
                        ? usageTheme.pillActive
                        : disabled
                          ? 'border-transparent text-gray-400 cursor-not-allowed opacity-60'
                          : usageTheme.pillInactive
                    }`}
                  >
                    {k.label}
                  </button>
                )
              })}
              {!availableKinds.has('tts') ? (
                <span className="text-xs text-gray-400">No TTS</span>
              ) : null}
              {!availableKinds.has('stt') ? (
                <span className="text-xs text-gray-400">No STT</span>
              ) : null}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-500 shrink-0">Model</span>
                <select
                  value={model}
                  onChange={(e) => onModelChange(e.target.value)}
                  className={`rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm min-w-[12rem] max-w-[20rem] ${usageTheme.focusRing}`}
                >
                  <option value="">All models</option>
                  {models.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </label>
              {models.length === 0 ? (
                <span className="text-xs text-gray-400">No models in this range</span>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
