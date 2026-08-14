import { useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { Card, CardBody, Spinner } from '@heroui/react'
import { Activity, ChevronRight, CircleDollarSign } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { useIsAdmin } from '../../hooks/useRole'
import UsageFiltersBar from './UsageFiltersBar'
import UsageDrillPath from './UsageDrillPath'
import UsageCostBreakdownModal from './UsageCostBreakdownModal'
import { defaultUsageDateRange, isRangeWithinMaxDays, rangeForDays } from './UsageDateRangePicker'
import { getUsageTimezone } from './usageTimezone'
import { useLicenseStore } from '../../store/licenseStore'
import {
  CALL_IMPORT_BATCH_HEADLINE,
  CALL_IMPORT_HINT,
  CALL_IMPORT_PRODUCT_SECTIONS,
  PRODUCT_SECTION_HEADLINES,
  PRODUCT_SECTION_HINTS,
  USAGE_SECTION_SOURCE_PREFIX,
} from './usageProductHints'

type DrillGroupBy =
  | 'workspace'
  | 'call_import'
  | 'resource'
  | 'model'
  | 'usage_kind'
  | 'product_section'
type Kind = '' | 'llm' | 'stt' | 'tts'

type FilterOptions = {
  workspaces: Array<{ id: string; name: string }>
  call_imports: Array<{ id: string; label: string }>
  evaluations: Array<{ id: string; label: string }>
  resources?: Array<{ id: string; label: string; type?: string; product_section?: string }>
  models: string[]
  usage_kinds: Array<{ id: string; label: string }>
  product_sections?: Array<{ id: string; label: string }>
  datasets?: string[]
  tags?: Array<{ id: string; label: string }>
}

type UsageCosts = {
  input_cost_usd: number
  output_cost_usd: number
  cache_read_cost_usd: number
  cache_write_cost_usd: number
  reasoning_cost_usd: number
  audio_cost_usd: number
  tts_cost_usd: number
  total_cost_usd: number
  currency: string
  has_unpriced_usage: boolean
}

type BreakdownRow = {
  workspace_id?: string | null
  workspace_name?: string | null
  call_import_id?: string | null
  call_import_label?: string | null
  resource_id?: string | null
  resource_type?: string | null
  resource_label?: string | null
  model?: string | null
  usage_kind?: string | null
  product_section?: string | null
  product_section_label?: string | null
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cache_read_tokens: number
  cache_creation_tokens: number
  reasoning_tokens: number
  audio_seconds: number
  tts_characters: number
  call_count: number
  input_cost_micro_usd?: number
  output_cost_micro_usd?: number
  cache_read_cost_micro_usd?: number
  cache_creation_cost_micro_usd?: number
  reasoning_cost_micro_usd?: number
  audio_cost_micro_usd?: number
  tts_cost_micro_usd?: number
  total_cost_micro_usd?: number
  costs?: UsageCosts
}

type WorkspaceSourceRow = BreakdownRow & {
  rowKind: 'call_import' | 'workspace_resource'
  hint: string
}

const NON_COMPOSITE_RESOURCE_TYPES = new Set([
  'call_import',
  'call_import_evaluation',
])

type TableRow = BreakdownRow | WorkspaceSourceRow

const EMPTY_METRICS = {
  prompt_tokens: 0,
  completion_tokens: 0,
  total_tokens: 0,
  cache_read_tokens: 0,
  cache_creation_tokens: 0,
  reasoning_tokens: 0,
  audio_seconds: 0,
  tts_characters: 0,
  call_count: 0,
  input_cost_micro_usd: 0,
  output_cost_micro_usd: 0,
  cache_read_cost_micro_usd: 0,
  cache_creation_cost_micro_usd: 0,
  reasoning_cost_micro_usd: 0,
  audio_cost_micro_usd: 0,
  tts_cost_micro_usd: 0,
  total_cost_micro_usd: 0,
  costs: {
    input_cost_usd: 0,
    output_cost_usd: 0,
    cache_read_cost_usd: 0,
    cache_write_cost_usd: 0,
    reasoning_cost_usd: 0,
    audio_cost_usd: 0,
    tts_cost_usd: 0,
    total_cost_usd: 0,
    currency: 'USD',
    has_unpriced_usage: false,
  },
}

function compositeRowHeadline(row: WorkspaceSourceRow): string {
  if (row.rowKind === 'call_import') return CALL_IMPORT_BATCH_HEADLINE
  const section = row.product_section || ''
  return (
    PRODUCT_SECTION_HEADLINES[section] ||
    row.product_section_label ||
    section ||
    'Other'
  )
}

function usableResourceLabel(label: string | null | undefined): string | undefined {
  if (!label || label === 'Unscoped') return undefined
  return label
}

function compositeRowTitle(row: WorkspaceSourceRow, options?: FilterOptions): string {
  if (row.rowKind === 'call_import') {
    return row.call_import_label || 'Call import batch'
  }
  const fromFilters = row.resource_id
    ? options?.resources?.find((r) => idKey(r.id) === idKey(row.resource_id))?.label
    : undefined
  return (
    usableResourceLabel(row.resource_label) ||
    fromFilters ||
    row.product_section_label ||
    'Unscoped usage'
  )
}

function sortRows(rows: BreakdownRow[]): BreakdownRow[] {
  return [...rows].sort((a, b) => b.total_tokens - a.total_tokens)
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value || 0)
}

function formatCostUsd(usd?: number | null): string {
  const amount = Number(usd || 0)
  if (!amount) return '—'
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(amount)
}

function rowCostUsd(row: Pick<BreakdownRow, 'costs' | 'total_cost_micro_usd'>): number {
  if (row.costs?.total_cost_usd != null) return row.costs.total_cost_usd
  return Number(row.total_cost_micro_usd || 0) / 1_000_000
}

function formatAudio(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0))
  if (total < 60) return `${total}s`
  const mins = Math.floor(total / 60)
  const secs = total % 60
  if (mins < 60) return secs ? `${mins}m ${secs}s` : `${mins}m`
  const hours = Math.floor(mins / 60)
  const remMins = mins % 60
  return remMins ? `${hours}h ${remMins}m` : `${hours}h`
}

function rowHasUsageForKind(row: BreakdownRow, kind: Kind): boolean {
  if (!kind) return true
  if (kind === 'llm') {
    return (row.total_tokens ?? 0) > 0 || (row.call_count ?? 0) > 0
  }
  if (kind === 'stt') {
    return (row.audio_seconds ?? 0) > 0 || (row.call_count ?? 0) > 0
  }
  if (kind === 'tts') {
    return (row.tts_characters ?? 0) > 0 || (row.call_count ?? 0) > 0
  }
  return true
}

function filterRowsForUsageKind(rows: BreakdownRow[], kind: Kind): BreakdownRow[] {
  if (!kind) return rows
  return rows.filter((row) => rowHasUsageForKind(row, kind))
}

function rowHasAnyUsage(row: BreakdownRow): boolean {
  return (
    (row.total_tokens ?? 0) > 0 ||
    (row.call_count ?? 0) > 0 ||
    (row.audio_seconds ?? 0) > 0 ||
    (row.tts_characters ?? 0) > 0
  )
}

function isUsageScopeActive(
  workspaceId: string,
  callImportId: string,
  evaluationId: string,
  dataset: string,
  tagId: string,
  usageKind: Kind,
  model: string,
  productSection: string,
): boolean {
  return Boolean(
    workspaceId ||
      callImportId ||
      evaluationId ||
      dataset ||
      tagId ||
      usageKind ||
      model ||
      productSection,
  )
}

/** Drop zero rows when any filter is active; kind filter uses kind-specific metrics. */
function filterTableRows(
  rows: BreakdownRow[],
  usageKind: Kind,
  scopeActive: boolean,
): BreakdownRow[] {
  if (usageKind) return filterRowsForUsageKind(rows, usageKind)
  if (scopeActive) return rows.filter(rowHasAnyUsage)
  return rows
}

function drillGroupBy(
  workspaceId: string,
  callImportId: string,
  evaluationId: string,
  model: string,
  productSection: string,
): DrillGroupBy {
  if (productSection && model) return 'usage_kind'
  if (productSection) return 'model'
  if (evaluationId && model) return 'usage_kind'
  if (evaluationId) return 'model'
  if (callImportId) return 'resource'
  if (workspaceId) return 'call_import'
  return 'workspace'
}

function enrichCallImportRows(
  rawRows: BreakdownRow[],
  options?: FilterOptions,
): BreakdownRow[] {
  const labelById = new Map(
    (options?.call_imports ?? []).map((c) => [idKey(c.id), c.label]),
  )
  return sortRows(
    rawRows
      .filter((r) => r.call_import_id)
      .map((row) => {
        const key = idKey(row.call_import_id)
        return {
          ...row,
          call_import_label:
            labelById.get(key) || row.call_import_label || 'Call import',
        }
      }),
  )
}

function buildWorkspaceCompositeRows(
  callImportRaw: BreakdownRow[],
  resourceRaw: BreakdownRow[],
  options?: FilterOptions,
  padMissingRows = true,
): WorkspaceSourceRow[] {
  const resourceLabelById = new Map(
    (options?.resources ?? []).map((r) => [idKey(r.id), r.label]),
  )
  const importRows = enrichCallImportRows(callImportRaw, options)
  const rows: WorkspaceSourceRow[] = []
  const shownImportIds = new Set<string>()

  for (const row of importRows) {
    if (!row.call_import_id) continue
    shownImportIds.add(idKey(row.call_import_id))
    rows.push({
      ...row,
      rowKind: 'call_import',
      hint: CALL_IMPORT_HINT,
    })
  }

  if (padMissingRows) {
    for (const ci of options?.call_imports ?? []) {
      const key = idKey(ci.id)
      if (shownImportIds.has(key)) continue
      shownImportIds.add(key)
      rows.push({
        call_import_id: ci.id,
        call_import_label: ci.label,
        ...EMPTY_METRICS,
        rowKind: 'call_import',
        hint: CALL_IMPORT_HINT,
      })
    }
  }

  for (const row of resourceRaw) {
    const section = row.product_section
    if (!section || CALL_IMPORT_PRODUCT_SECTIONS.has(section)) continue
    if (NON_COMPOSITE_RESOURCE_TYPES.has(row.resource_type || '')) continue
    if (
      row.total_tokens === 0 &&
      row.call_count === 0 &&
      !row.audio_seconds &&
      !row.tts_characters
    ) {
      continue
    }
    if (!rowHasAnyUsage(row)) {
      continue
    }
    rows.push({
      ...row,
      rowKind: 'workspace_resource',
      product_section: section,
      product_section_label: row.product_section_label || section,
      resource_label:
        resourceLabelById.get(idKey(row.resource_id)) ||
        usableResourceLabel(row.resource_label),
      hint: PRODUCT_SECTION_HINTS[section] || 'Product usage',
    })
  }

  return sortRows(rows) as WorkspaceSourceRow[]
}

function drillColumnLabel(groupBy: DrillGroupBy, composite = false): string {
  if (composite) return 'Source'
  if (groupBy === 'workspace') return 'Workspace'
  if (groupBy === 'call_import') return 'Call import'
  if (groupBy === 'resource') return 'Evaluation run'
  if (groupBy === 'product_section') return 'Product area'
  if (groupBy === 'model') return 'Model'
  return 'Kind'
}

function rowLabel(groupBy: DrillGroupBy, row: BreakdownRow, options?: FilterOptions): string {
  if (groupBy === 'workspace') return row.workspace_name || 'Unknown'
  if (groupBy === 'call_import') return row.call_import_label || 'Call import'
  if (groupBy === 'resource') {
    const fromFilters = row.resource_id
      ? options?.resources?.find((r) => idKey(r.id) === idKey(row.resource_id))?.label
      : undefined
    return (
      usableResourceLabel(row.resource_label) || fromFilters || 'Unscoped'
    )
  }
  if (groupBy === 'model') return row.model || '—'
  if (groupBy === 'product_section')
    return row.product_section_label || row.product_section || '—'
  if (row.usage_kind === 'stt') return 'STT'
  if (row.usage_kind === 'llm') return 'LLM'
  if (row.usage_kind === 'tts') return 'TTS'
  return row.usage_kind || '—'
}

function tableRowLabel(
  groupBy: DrillGroupBy,
  row: TableRow,
  options?: FilterOptions,
): string {
  if ('rowKind' in row) {
    if (row.rowKind === 'call_import') return row.call_import_label || 'Call import batch'
    return compositeRowTitle(row, options)
  }
  return rowLabel(groupBy, row, options)
}

function idInOptions(
  id: string,
  options: Array<{ id: string }> | undefined,
): boolean {
  if (!id || !options?.length) return false
  const key = idKey(id)
  return options.some((o) => idKey(o.id) === key)
}

function idKey(id: string | null | undefined): string {
  return id ? String(id).toLowerCase() : ''
}

function mergeDrillRows(
  groupBy: DrillGroupBy,
  rawRows: BreakdownRow[],
  options?: FilterOptions,
  padMissingRows = true,
): BreakdownRow[] {
  if (groupBy === 'workspace' && options?.workspaces?.length && padMissingRows) {
    const byId = new Map(
      rawRows
        .filter((r) => r.workspace_id)
        .map((r) => [idKey(r.workspace_id), r]),
    )
    const merged: BreakdownRow[] = options.workspaces.map((ws) => ({
      workspace_id: ws.id,
      workspace_name: ws.name,
      ...(byId.get(idKey(ws.id)) ?? EMPTY_METRICS),
    }))
    for (const row of rawRows) {
      if (!row.workspace_id) {
        merged.push({
          ...row,
          workspace_name: row.workspace_name || 'No workspace',
        })
      }
    }
    return sortRows(merged)
  }

  if (groupBy === 'call_import') {
    if (rawRows.length === 0) return []

    const labelById = new Map(
      (options?.call_imports ?? []).map((c) => [idKey(c.id), c.label]),
    )
    const shown = new Set<string>()
    const merged: BreakdownRow[] = []

    for (const row of rawRows) {
      if (row.call_import_id) {
        const key = idKey(row.call_import_id)
        shown.add(key)
        merged.push({
          ...row,
          call_import_label:
            labelById.get(key) || row.call_import_label || 'Call import',
        })
      }
    }

    if (padMissingRows) {
      for (const ci of options?.call_imports ?? []) {
        const key = idKey(ci.id)
        if (!shown.has(key)) {
          merged.push({
            call_import_id: ci.id,
            call_import_label: ci.label,
            ...EMPTY_METRICS,
          })
        }
      }
    }

    return sortRows(merged)
  }

  if (groupBy === 'resource') {
    if (rawRows.length === 0) return []

    const evalLabelById = new Map(
      (options?.evaluations ?? []).map((e) => [idKey(e.id), e.label]),
    )
    const resourceLabelById = new Map(
      (options?.resources ?? []).map((r) => [idKey(r.id), r.label]),
    )
    const shown = new Set<string>()
    const merged: BreakdownRow[] = []

    for (const row of rawRows) {
      if (row.resource_id) {
        const key = idKey(row.resource_id)
        shown.add(key)
        merged.push({
          ...row,
          resource_label:
            resourceLabelById.get(key) ||
            evalLabelById.get(key) ||
            usableResourceLabel(row.resource_label) ||
            'Evaluation',
        })
      }
    }

    if (padMissingRows) {
      for (const ev of options?.evaluations ?? []) {
        const key = idKey(ev.id)
        if (!shown.has(key)) {
          merged.push({
            resource_id: ev.id,
            resource_label: ev.label,
            ...EMPTY_METRICS,
          })
        }
      }
    }

    return sortRows(merged)
  }

  if (groupBy === 'model' && options?.models?.length && padMissingRows) {
    if (rawRows.length === 0) return []
    const byName = new Map(
      rawRows.filter((r) => r.model).map((r) => [r.model!, r]),
    )
    const merged = options.models.map((name) => ({
      model: name,
      ...(byName.get(name) ?? EMPTY_METRICS),
    }))
    return sortRows(merged)
  }

  if (groupBy === 'usage_kind') {
    return sortRows(
      rawRows.filter((row) => rowHasUsageForKind(row, row.usage_kind as Kind)),
    )
  }

  return sortRows(rawRows)
}

export default function Usage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const defaultRange = useMemo(() => defaultUsageDateRange(), [])
  const usageTimezone = useMemo(() => getUsageTimezone(), [])

  const start = searchParams.get('start') || defaultRange.start
  const end = searchParams.get('end') || defaultRange.end
  const workspaceId = searchParams.get('workspace_id') || ''
  const callImportId = searchParams.get('call_import_id') || ''
  const dataset = searchParams.get('dataset') || ''
  const tagId = searchParams.get('tag_id') || ''
  const evaluationId = searchParams.get('resource_id') || ''
  const model = searchParams.get('model') || ''
  const usageKind = (searchParams.get('usage_kind') as Kind) || ''
  const productSection = searchParams.get('product_section') || ''
  const isAdmin = useIsAdmin()
  const { usagePolicy, isLoaded: licenseLoaded, fetchLicense } = useLicenseStore()
  const showOssUsageNotice = licenseLoaded && !usagePolicy.extended_history
  const maxHistoryDays = !licenseLoaded
    ? null
    : usagePolicy.extended_history
      ? null
      : usagePolicy.max_history_days ?? 7
  const [costBreakdownOpen, setCostBreakdownOpen] = useState(false)

  useEffect(() => {
    if (!licenseLoaded) {
      void fetchLicense()
    }
  }, [licenseLoaded, fetchLicense])

  useEffect(() => {
    if (!licenseLoaded || usagePolicy.extended_history) return
    const maxDays = usagePolicy.max_history_days ?? 7
    if (!isRangeWithinMaxDays(start, end, maxDays)) {
      const r = rangeForDays(maxDays)
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        next.set('start', r.start)
        next.set('end', r.end)
        return next
      })
    }
  }, [licenseLoaded, usagePolicy.extended_history, usagePolicy.max_history_days, start, end, setSearchParams])

  const showWorkspaceComposite =
    Boolean(workspaceId) &&
    !callImportId &&
    !evaluationId &&
    !productSection

  const groupBy = drillGroupBy(
    workspaceId,
    callImportId,
    evaluationId,
    model,
    productSection,
  )

  const setParams = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(updates)) {
      if (!value) next.delete(key)
      else next.set(key, value)
    }
    setSearchParams(next)
  }

  const scopeParams = {
    start,
    end,
    tz: usageTimezone,
    workspace_id: workspaceId || undefined,
    call_import_id: callImportId || undefined,
    dataset: dataset || undefined,
    tag_id: tagId || undefined,
    product_section: productSection || undefined,
    usage_kind: usageKind || undefined,
    model: model || undefined,
    resource_id: evaluationId || undefined,
  }

  const dataParams = {
    ...scopeParams,
    evaluation_id: callImportId ? evaluationId || undefined : undefined,
  }

  const usageQueryDefaults = {
    staleTime: 60 * 1000,
  }

  const catalogSync = useQuery({
    queryKey: ['org-usage', 'catalog-sync'],
    queryFn: () => apiClient.syncOrgUsageCatalog(),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  })

  const usageReadsReady = catalogSync.isSuccess || catalogSync.isError

  const { data: summary, isLoading: summaryLoading, isFetching: summaryFetching } = useQuery({
    queryKey: ['org-usage', 'summary', dataParams],
    queryFn: () => apiClient.getOrgUsageSummary(dataParams),
    enabled: usageReadsReady,
    ...usageQueryDefaults,
    placeholderData: keepPreviousData,
  })

  const usageStatsLoading = catalogSync.isLoading || summaryLoading

  const {
    data: breakdown,
    isLoading: breakdownLoading,
    isFetching: breakdownFetching,
  } = useQuery({
    queryKey: ['org-usage', 'breakdown', groupBy, dataParams],
    queryFn: () =>
      apiClient.getOrgUsageBreakdown({
        ...dataParams,
        group_by: groupBy,
        limit: 100,
      }),
    enabled: usageReadsReady && !showWorkspaceComposite,
    ...usageQueryDefaults,
    placeholderData: (previousData, previousQuery) => {
      if (!previousQuery || previousQuery.queryKey[2] !== groupBy) return undefined
      return previousData
    },
  })

  const {
    data: importBreakdown,
    isLoading: importBreakdownLoading,
    isFetching: importBreakdownFetching,
  } = useQuery({
    queryKey: ['org-usage', 'breakdown', 'call_import', dataParams],
    queryFn: () =>
      apiClient.getOrgUsageBreakdown({
        ...dataParams,
        group_by: 'call_import',
        limit: 100,
      }),
    enabled: usageReadsReady && showWorkspaceComposite,
    ...usageQueryDefaults,
  })

  const {
    data: resourceBreakdown,
    isLoading: resourceBreakdownLoading,
    isFetching: resourceBreakdownFetching,
  } = useQuery({
    queryKey: ['org-usage', 'breakdown', 'resource', dataParams],
    queryFn: () =>
      apiClient.getOrgUsageBreakdown({
        ...dataParams,
        group_by: 'resource',
        limit: 100,
      }),
    enabled: usageReadsReady && showWorkspaceComposite,
    ...usageQueryDefaults,
  })

  const { data: filterOptions, isFetching: filtersLoading } = useQuery({
    queryKey: ['org-usage', 'filters', scopeParams],
    queryFn: () => apiClient.getOrgUsageFilters(scopeParams),
    enabled: usageReadsReady,
    staleTime: 60 * 1000,
    placeholderData: (previousData, previousQuery) => {
      if (!previousQuery) return undefined
      const prevScope = previousQuery.queryKey[2] as typeof scopeParams
      if (JSON.stringify(prevScope) !== JSON.stringify(scopeParams)) return undefined
      return previousData
    },
  })

  useEffect(() => {
    if (!filterOptions) return
    const updates: Record<string, string | null> = {}
    if (
      workspaceId &&
      !idInOptions(workspaceId, filterOptions.workspaces)
    ) {
      updates.workspace_id = null
      updates.call_import_id = null
      updates.resource_id = null
      updates.product_section = null
    }
    if (
      callImportId &&
      !idInOptions(callImportId, filterOptions.call_imports)
    ) {
      updates.call_import_id = null
      updates.resource_id = null
      updates.product_section = null
    }
    if (
      evaluationId &&
      !idInOptions(evaluationId, filterOptions.evaluations) &&
      !idInOptions(evaluationId, filterOptions.resources)
    ) {
      updates.resource_id = null
      updates.product_section = null
    }
    if (model && !filterOptions.models?.includes(model)) {
      updates.model = null
    }
    if (
      usageKind &&
      !filterOptions.usage_kinds?.some((k) => k.id === usageKind)
    ) {
      updates.usage_kind = null
    }
    if (
      productSection &&
      !filterOptions.product_sections?.some((s) => s.id === productSection)
    ) {
      updates.product_section = null
    }
    if (dataset && !filterOptions.datasets?.includes(dataset)) {
      updates.dataset = null
    }
    if (tagId && !idInOptions(tagId, filterOptions.tags)) {
      updates.tag_id = null
    }
    if (Object.keys(updates).length > 0) setParams(updates)
  }, [
    filterOptions,
    workspaceId,
    callImportId,
    dataset,
    tagId,
    evaluationId,
    model,
    usageKind,
    productSection,
  ])

  const breakdownMatchesLevel = breakdown?.group_by === groupBy
  const rawRows = useMemo((): BreakdownRow[] => {
    if (!breakdown || !breakdownMatchesLevel) return []
    return breakdown.rows as BreakdownRow[]
  }, [breakdown, breakdownMatchesLevel])

  const mergeOptions = filterOptions
  const scopeActive = isUsageScopeActive(
    workspaceId,
    callImportId,
    evaluationId,
    dataset,
    tagId,
    usageKind,
    model,
    productSection,
  )
  const padMissingRows = !scopeActive
  const filteredRawRows = useMemo(
    () => filterTableRows(rawRows, usageKind, scopeActive),
    [rawRows, usageKind, scopeActive],
  )
  const rows: TableRow[] = useMemo(() => {
    if (showWorkspaceComposite) {
      const importReady = importBreakdown?.group_by === 'call_import'
      const resourceReady = resourceBreakdown?.group_by === 'resource'
      if (!importReady && !resourceReady) return []
      return buildWorkspaceCompositeRows(
        importReady
          ? filterTableRows(importBreakdown.rows as BreakdownRow[], usageKind, scopeActive)
          : [],
        resourceReady
          ? filterTableRows(resourceBreakdown.rows as BreakdownRow[], usageKind, scopeActive)
          : [],
        mergeOptions,
        padMissingRows,
      )
    }
    return mergeDrillRows(groupBy, filteredRawRows, mergeOptions, padMissingRows)
  }, [
    showWorkspaceComposite,
    importBreakdown,
    resourceBreakdown,
    groupBy,
    filteredRawRows,
    mergeOptions,
    padMissingRows,
    usageKind,
    scopeActive,
  ])

  const breakdownStale =
    !showWorkspaceComposite && breakdownFetching && !breakdownMatchesLevel
  const tableLoading = showWorkspaceComposite
    ? (importBreakdownLoading || resourceBreakdownLoading) &&
      !importBreakdown &&
      !resourceBreakdown
    : breakdownLoading && !breakdown
  const tableFetching = showWorkspaceComposite
    ? importBreakdownFetching || resourceBreakdownFetching
    : breakdownFetching
  const totals = summary?.totals
  const estimatedTotalCost =
    totals?.costs?.total_cost_usd ?? (totals?.total_cost_micro_usd || 0) / 1_000_000
  const showCostBreakdown =
    estimatedTotalCost > 0 || Boolean(totals?.costs?.has_unpriced_usage)
  const showAudio = Boolean(totals?.audio_seconds)
  const showTts =
    Boolean(totals?.tts_characters) ||
    rows.some((r) => Boolean(r.tts_characters))

  const showTruncation =
    (!showWorkspaceComposite &&
      breakdownMatchesLevel &&
      Boolean(breakdown?.truncated_at_limit)) ||
    (showWorkspaceComposite &&
      Boolean(
        importBreakdown?.truncated_at_limit || resourceBreakdown?.truncated_at_limit,
      ))

  const workspaceLabel =
    filterOptions?.workspaces?.find((w) => idKey(w.id) === idKey(workspaceId))?.name
  const callImportLabel =
    filterOptions?.call_imports?.find((c) => idKey(c.id) === idKey(callImportId))?.label
  const evaluationLabel =
    filterOptions?.resources?.find((r) => idKey(r.id) === idKey(evaluationId))?.label ||
    filterOptions?.evaluations?.find((e) => idKey(e.id) === idKey(evaluationId))?.label

  const productSectionLabel =
    filterOptions?.product_sections?.find((s) => s.id === productSection)?.label

  const scopeSubtitle = model
    ? model
    : evaluationId
      ? evaluationLabel || 'Evaluation'
      : callImportId
        ? callImportLabel || 'Call import'
        : productSection
          ? productSectionLabel || 'Product area'
          : workspaceId
            ? workspaceLabel || 'Workspace'
            : 'Organization'

  const levelHint = (() => {
    if (showWorkspaceComposite) {
      return 'Call import batches and other product usage — click a row to drill down'
    }
    if (groupBy === 'workspace') return 'Click a workspace to drill down'
    if (groupBy === 'call_import') return 'Click a call import to see evaluation runs'
    if (groupBy === 'product_section') return 'Click a product area to see models used'
    if (groupBy === 'resource') return 'Click an evaluation to see models used'
    if (groupBy === 'model') return 'Click a model to see usage by kind'
    return 'Token totals by LLM / STT / TTS'
  })()

  const drillCrumbs = [
    {
      label: 'Organization',
      onClick:
        workspaceId ||
        callImportId ||
        evaluationId ||
        model ||
        productSection
          ? () =>
              setParams({
                workspace_id: null,
                call_import_id: null,
                resource_id: null,
                model: null,
                usage_kind: null,
                product_section: null,
              })
          : undefined,
    },
    ...(workspaceId
      ? [
          {
            label: workspaceLabel || 'Workspace',
            onClick:
              callImportId || evaluationId || model || productSection
                ? () =>
                    setParams({
                      call_import_id: null,
                      resource_id: null,
                      model: null,
                      usage_kind: null,
                      product_section: null,
                    })
                : undefined,
          },
        ]
      : []),
    ...(productSection
      ? [
          {
            label: productSectionLabel || 'Product area',
            onClick:
              model
                ? () => setParams({ model: null, usage_kind: null })
                : undefined,
          },
        ]
      : []),
    ...(callImportId
      ? [
          {
            label: callImportLabel || 'Call import',
            onClick:
              evaluationId || model
                ? () =>
                    setParams({
                      resource_id: null,
                      model: null,
                      usage_kind: null,
                      product_section: null,
                    })
                : undefined,
          },
        ]
      : []),
    ...(evaluationId
      ? [
          {
            label: evaluationLabel || 'Evaluation',
            onClick: model
              ? () => setParams({ model: null, usage_kind: null })
              : undefined,
          },
        ]
      : []),
    ...(model ? [{ label: model }] : []),
  ]

  const handleWorkspaceChange = (id: string) => {
    setParams({
      workspace_id: id || null,
      call_import_id: null,
      resource_id: null,
      model: null,
      usage_kind: null,
      product_section: null,
    })
  }

  const handleCallImportChange = (id: string) => {
    setParams({
      call_import_id: id || null,
      resource_id: null,
      model: null,
      usage_kind: null,
      product_section: null,
    })
  }

  const handleClearAll = () => {
    setParams({
      workspace_id: null,
      call_import_id: null,
      dataset: null,
      tag_id: null,
      resource_id: null,
      usage_kind: null,
      model: null,
      product_section: null,
    })
  }

  const handleRowDrill = (row: TableRow) => {
    if ('rowKind' in row) {
      if (row.rowKind === 'call_import' && row.call_import_id) {
        setParams({
          call_import_id: row.call_import_id,
          resource_id: null,
          model: null,
          usage_kind: null,
          product_section: null,
        })
        return
      }
      if (row.rowKind === 'workspace_resource' && row.product_section) {
        setParams({
          product_section: row.product_section,
          call_import_id: null,
          resource_id: row.resource_id || null,
          model: null,
          usage_kind: null,
        })
        return
      }
    }
    if (groupBy === 'workspace' && row.workspace_id) {
      setParams({
        workspace_id: row.workspace_id,
        call_import_id: null,
        resource_id: null,
        model: null,
        usage_kind: null,
        product_section: null,
      })
      return
    }
    if (groupBy === 'call_import' && row.call_import_id) {
      setParams({
        call_import_id: row.call_import_id,
        resource_id: null,
        model: null,
        usage_kind: null,
        product_section: null,
      })
      return
    }
    if (groupBy === 'product_section' && row.product_section) {
      setParams({
        product_section: row.product_section,
        call_import_id: null,
        resource_id: null,
        model: null,
        usage_kind: null,
      })
      return
    }
    if (groupBy === 'resource' && row.resource_id) {
      setParams({
        resource_id: row.resource_id,
        model: null,
        usage_kind: null,
        product_section: null,
      })
      return
    }
    if (groupBy === 'model' && row.model) {
      setParams({ model: row.model, usage_kind: null })
    }
  }

  const isRowDrillable = (row: TableRow): boolean => {
    if ('rowKind' in row) {
      if (row.rowKind === 'call_import') return Boolean(row.call_import_id)
      return Boolean(row.product_section)
    }
    if (groupBy === 'workspace') return Boolean(row.workspace_id)
    if (groupBy === 'call_import') return Boolean(row.call_import_id)
    if (groupBy === 'product_section') return Boolean(row.product_section)
    if (groupBy === 'resource') return Boolean(row.resource_id)
    if (groupBy === 'model') return Boolean(row.model)
    return false
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Activity className="h-6 w-6 text-primary-600 shrink-0" />
            Usage
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Cards show usage for <span className="font-medium text-gray-700">{scopeSubtitle}</span>.
            Drill down: workspaces → call imports or product areas → evaluations / models.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <div className="flex items-center gap-3">
            {showCostBreakdown ? (
              <button
                type="button"
                onClick={() => setCostBreakdownOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 shadow-sm transition-colors hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900"
                title={formatCostUsd(estimatedTotalCost)}
              >
                <CircleDollarSign className="h-4 w-4 shrink-0 text-gray-500" />
                <span className="whitespace-nowrap">Cost breakdown</span>
              </button>
            ) : null}
            {isAdmin && licenseLoaded && usagePolicy.extended_history ? (
              <Link
                to="/usage/pricing"
                className="text-sm text-primary-600 hover:text-primary-700 whitespace-nowrap"
              >
                Pricing overrides
              </Link>
            ) : null}
          </div>
          {summary?.last_updated_at ? (
            <p className="text-[11px] text-gray-400 whitespace-nowrap">
              Updated {new Date(summary.last_updated_at).toLocaleString()}
            </p>
          ) : null}
        </div>
      </div>

      {showOssUsageNotice ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Showing the last {maxHistoryDays} days of usage history. Set{' '}
          <code className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-mono">
            EFFICIENTAI_LICENSE
          </code>{' '}
          on your server with any enterprise feature to unlock extended history.
        </div>
      ) : null}

      <div
        className={`space-y-3 transition-opacity ${summaryFetching ? 'opacity-70' : ''}`}
      >
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Input tokens" value={totals?.prompt_tokens} loading={usageStatsLoading} />
          <StatCard label="Output tokens" value={totals?.completion_tokens} loading={usageStatsLoading} />
          <StatCard label="Total tokens" value={totals?.total_tokens} loading={usageStatsLoading} />
          <StatCard label="LLM calls" value={totals?.call_count} loading={usageStatsLoading} />
        </div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 md:items-stretch">
          <div className="col-span-2 grid grid-cols-2 gap-3 sm:grid-cols-3 md:col-span-3">
            {showAudio ? (
              <StatCard
                label="STT audio"
                valueLabel={formatAudio(totals?.audio_seconds || 0)}
                loading={usageStatsLoading}
              />
            ) : null}
            {showTts ? (
              <StatCard label="TTS characters" value={totals?.tts_characters} loading={usageStatsLoading} />
            ) : null}
            {(totals?.cache_read_tokens || 0) > 0 ? (
              <StatCard label="Cache read" value={totals?.cache_read_tokens} loading={usageStatsLoading} />
            ) : null}
            {(totals?.cache_creation_tokens || 0) > 0 ? (
              <StatCard
                label="Cache write"
                value={totals?.cache_creation_tokens}
                loading={usageStatsLoading}
              />
            ) : null}
            {(totals?.reasoning_tokens || 0) > 0 ? (
              <StatCard label="Reasoning" value={totals?.reasoning_tokens} loading={usageStatsLoading} />
            ) : null}
          </div>
          <div className="col-span-2 md:col-span-1">
            <StatCard
              label="Estimated cost"
              valueLabel={formatCostUsd(estimatedTotalCost)}
              loading={usageStatsLoading}
              emphasize
            />
          </div>
        </div>
      </div>

      <UsageFiltersBar
        start={start}
        end={end}
        workspaceId={workspaceId}
        callImportId={callImportId}
        evaluationId={evaluationId}
        dataset={dataset}
        tagId={tagId}
        usageKind={usageKind}
        model={model}
        productSection={productSection}
        options={filterOptions}
        filtersLoading={filtersLoading}
        onDateApply={(s, e) => setParams({ start: s, end: e })}
        onWorkspaceChange={handleWorkspaceChange}
        onCallImportChange={handleCallImportChange}
        onDatasetChange={(v) =>
          setParams({
            dataset: v || null,
            call_import_id: null,
            resource_id: null,
          })
        }
        onTagChange={(v) =>
          setParams({
            tag_id: v || null,
            call_import_id: null,
            resource_id: null,
          })
        }
        onEvaluationChange={(id) => {
          if (id.startsWith(USAGE_SECTION_SOURCE_PREFIX)) {
            const section = id.slice(USAGE_SECTION_SOURCE_PREFIX.length)
            setParams({
              product_section: section || null,
              resource_id: null,
              call_import_id: null,
              model: null,
              usage_kind: null,
            })
            return
          }
          const resource = filterOptions?.resources?.find(
            (r) => idKey(r.id) === idKey(id),
          )
          setParams({
            resource_id: id || null,
            product_section: id ? resource?.product_section || null : null,
            model: null,
            usage_kind: null,
          })
        }}
        onUsageKindChange={(k) => setParams({ usage_kind: k || null })}
        onModelChange={(v) => setParams({ model: v || null })}
        onClearAll={handleClearAll}
        maxHistoryDays={maxHistoryDays}
      />

      <Card shadow="sm" className="border border-gray-200 ring-1 ring-[#fde047]/25">
        <div className="border-b border-gray-100 px-4 py-3 space-y-2">
          <UsageDrillPath crumbs={drillCrumbs} levelLabel={levelHint} />
          {showTruncation ? (
            <p className="text-xs text-amber-700">
              Showing the first 100 rows for this level. Narrow the date range or drill
              further for complete detail.
            </p>
          ) : null}
        </div>
        <CardBody className="p-0 overflow-x-auto max-h-[min(70vh,640px)] overflow-y-auto custom-scrollbar">
          {tableLoading || breakdownStale ? (
            <div className="flex justify-center py-12">
              <Spinner />
            </div>
          ) : rows.length === 0 ? (
            <div className="py-12 text-center text-sm text-gray-500">
              No usage in this period for the current scope. Try 7d or 30d, or go back up a
              level.
            </div>
          ) : (
            <div
              className={`relative transition-opacity ${
                tableFetching ? 'opacity-60 pointer-events-none' : ''
              }`}
            >
              {tableFetching ? (
                <div className="absolute top-2 right-3 z-20">
                  <Spinner size="sm" />
                </div>
              ) : null}
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500 sticky top-0 z-10">
                <tr>
                  <th className="px-4 py-3 font-semibold">
                    {drillColumnLabel(groupBy, showWorkspaceComposite)}
                  </th>
                  <th className="px-4 py-3 font-semibold text-right">LLM calls</th>
                  <th className="px-4 py-3 font-semibold text-right">Input tokens</th>
                  <th className="px-4 py-3 font-semibold text-right">Output tokens</th>
                  <th className="px-4 py-3 font-semibold text-right">Total tokens</th>
                  <th className="px-4 py-3 font-semibold text-right">Est. cost</th>
                  <th className="px-4 py-3 font-semibold text-right">STT audio</th>
                  <th className="px-4 py-3 font-semibold text-right">TTS chars</th>
                  <th className="px-4 py-3 font-semibold text-right">Cache read</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {rows.map((row, idx) => {
                  const drillable = isRowDrillable(row)
                  const compositeHeadline =
                    'rowKind' in row ? compositeRowHeadline(row) : null
                  const rowTitle = tableRowLabel(groupBy, row, filterOptions)
                  const showRowTitle =
                    'rowKind' in row
                      ? row.rowKind === 'workspace_resource' ||
                        (compositeHeadline &&
                          rowTitle.toLowerCase() !== compositeHeadline.toLowerCase())
                      : true
                  return (
                    <tr
                      key={idx}
                      className={
                        drillable
                          ? 'hover:bg-[#fefce8]/60 cursor-pointer group'
                          : 'hover:bg-gray-50'
                      }
                      onClick={() => drillable && handleRowDrill(row)}
                    >
                      <td className="px-4 py-3 text-gray-900 max-w-md">
                        <span className="flex items-center gap-1 min-w-0">
                          <span className="min-w-0">
                            {'rowKind' in row ? (
                              <span className="block text-[10px] font-semibold uppercase tracking-wide text-primary-600 mb-0.5">
                                {compositeHeadline}
                              </span>
                            ) : null}
                            {showRowTitle ? (
                              <span className="truncate block font-medium">
                                {rowTitle}
                              </span>
                            ) : !('rowKind' in row) ? (
                              <span className="truncate block">{rowTitle}</span>
                            ) : null}
                            {'hint' in row && row.hint ? (
                              <span className="text-xs text-gray-400 truncate block">
                                {row.hint}
                              </span>
                            ) : null}
                          </span>
                          {drillable ? (
                            <ChevronRight
                              className="h-4 w-4 shrink-0 text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity"
                            />
                          ) : null}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatNumber(row.call_count)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatNumber(row.prompt_tokens)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatNumber(row.completion_tokens)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums font-medium">
                        {formatNumber(row.total_tokens)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                        {formatCostUsd(rowCostUsd(row))}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-500">
                        {row.audio_seconds ? formatAudio(row.audio_seconds) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-500">
                        {row.tts_characters ? formatNumber(row.tts_characters) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-500">
                        {formatNumber(row.cache_read_tokens)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            </div>
          )}
        </CardBody>
      </Card>

      <UsageCostBreakdownModal
        isOpen={costBreakdownOpen}
        onClose={() => setCostBreakdownOpen(false)}
        costs={totals?.costs}
        scopeLabel={scopeSubtitle}
      />
    </div>
  )
}

const statCardClass = 'border border-gray-200 ring-1 ring-[#fde047]/25 shadow-sm'

function StatCard({
  label,
  value,
  valueLabel,
  loading,
  emphasize = false,
  className = '',
}: {
  label: string
  value?: number
  valueLabel?: string
  loading?: boolean
  emphasize?: boolean
  className?: string
}) {
  return (
    <Card
      shadow="sm"
      className={`${statCardClass}${emphasize ? ' ring-2 ring-[#facc15]/50 bg-[#fefce8]/40' : ''} h-full w-full ${className}`}
    >
      <CardBody className="p-3">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
        <p
          className={`mt-0.5 text-xl font-semibold tabular-nums ${
            emphasize ? 'text-[#854d0e]' : 'text-gray-900'
          }`}
        >
          {loading ? '—' : valueLabel ?? formatNumber(value || 0)}
        </p>
      </CardBody>
    </Card>
  )
}
