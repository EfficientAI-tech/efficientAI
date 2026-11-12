import { useEffect, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Card, CardBody, Spinner } from '@heroui/react'
import { ChevronLeft, ChevronRight, CircleDollarSign } from 'lucide-react'
import { apiClient } from '../../lib/api'
import UsageFiltersBar from './UsageFiltersBar'
import UsageDrillPath from './UsageDrillPath'
import UsageCostBreakdownModal from './UsageCostBreakdownModal'
import { defaultUsageDateRange, isRangeWithinMaxDays, rangeForDays } from './UsageDateRangePicker'
import { getUsageTimezone } from './usageTimezone'
import {
  formatFxRateHint,
  formatUsageCostExactUsd,
  formatUsageCostUsd,
  getUsageDisplayCurrency,
  setUsageDisplayCurrency,
  type UsageDisplayCurrency,
} from '../../lib/usageCurrency'
import {
  formatAudioDuration,
  formatAudioExact,
  formatCompactCount,
  formatExactCount,
} from '../../lib/usageFormatters'
import UsageMetricValue from './UsageMetricValue'
import { useLicenseStore } from '../../store/licenseStore'
import {
  CALL_IMPORT_BATCH_HEADLINE,
  CALL_IMPORT_HINT,
  CALL_IMPORT_PRODUCT_SECTIONS,
  PRODUCT_SECTION_HEADLINES,
  PRODUCT_SECTION_HINTS,
  USAGE_SECTION_SOURCE_PREFIX,
} from './usageProductHints'
import { usageModelDisplayLabel, type UsageModelLabelContext } from './usageModelLabel'

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

const USAGE_TABLE_PAGE_SIZE = 100

async function fetchUsageGroupRows(
  params: Parameters<typeof apiClient.getOrgUsageBreakdown>[0],
  rowsNeeded: number,
  signal?: AbortSignal,
) {
  const rows: BreakdownRow[] = []
  let offset = 0
  let truncated = false
  let groupBy = params.group_by || ''
  while (rows.length < rowsNeeded) {
    const limit = Math.min(USAGE_TABLE_PAGE_SIZE, rowsNeeded - rows.length)
    const response = await apiClient.getOrgUsageBreakdown(
      { ...params, limit, offset },
      signal,
    )
    groupBy = response.group_by
    rows.push(...response.rows)
    truncated = Boolean(response.truncated_at_limit)
    if (!truncated || response.rows.length === 0) break
    offset += response.rows.length
  }
  return { rows, group_by: groupBy, truncated_at_limit: truncated }
}

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

function rowCostUsd(row: Pick<BreakdownRow, 'costs' | 'total_cost_micro_usd'>): number {
  if (row.costs?.total_cost_usd != null) return row.costs.total_cost_usd
  return Number(row.total_cost_micro_usd || 0) / 1_000_000
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
  if (groupBy === 'model') {
    return usageModelDisplayLabel(row.model, row)
  }
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
  const { usagePolicy, isLoaded: licenseLoaded, fetchLicense } = useLicenseStore()
  const showOssUsageNotice = licenseLoaded && !usagePolicy.extended_history
  const maxHistoryDays = !licenseLoaded
    ? null
    : usagePolicy.extended_history
      ? null
      : usagePolicy.max_history_days ?? 7
  const [costBreakdownOpen, setCostBreakdownOpen] = useState(false)
  const [drilledModelContext, setDrilledModelContext] = useState<
    UsageModelLabelContext | undefined
  >()
  const [displayCurrency, setDisplayCurrency] = useState<UsageDisplayCurrency>(() =>
    getUsageDisplayCurrency(),
  )

  const { data: fxRate } = useQuery({
    queryKey: ['org-usage', 'fx-rate'],
    queryFn: () => apiClient.getOrgUsageFxRate(),
    staleTime: 60 * 60 * 1000,
    refetchOnMount: 'always',
  })
  const inrRate = fxRate?.rate ?? 95
  const fxRateHint = formatFxRateHint(inrRate, fxRate?.as_of, fxRate?.source)
  const formatCostUsd = (usd?: number | null) =>
    formatUsageCostUsd(usd, displayCurrency, inrRate)
  const formatCostExact = (usd?: number | null) =>
    formatUsageCostExactUsd(usd, displayCurrency, inrRate)

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

  useEffect(() => {
    if (!model) setDrilledModelContext(undefined)
  }, [model])

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

  const [tablePage, setTablePage] = useState(1)
  const tableScrollRef = useRef<HTMLDivElement>(null)
  const tableScopeKey = [
    start,
    end,
    workspaceId,
    callImportId,
    dataset,
    tagId,
    evaluationId,
    model,
    usageKind,
    productSection,
    groupBy,
    showWorkspaceComposite ? '1' : '0',
  ].join('|')
  const tableScopeRef = useRef(tableScopeKey)
  if (tableScopeRef.current !== tableScopeKey) {
    tableScopeRef.current = tableScopeKey
    if (tablePage !== 1) setTablePage(1)
  }

  useEffect(() => {
    tableScrollRef.current?.scrollTo({ top: 0 })
  }, [tablePage])

  const usageQueryDefaults = {
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  }

  const {
    data: summary,
    isLoading: summaryLoading,
    isFetching: summaryFetching,
    isError: summaryError,
    error: summaryQueryError,
  } = useQuery({
    queryKey: ['org-usage', 'summary', dataParams],
    queryFn: ({ signal }) => apiClient.getOrgUsageSummary(dataParams, signal),
    ...usageQueryDefaults,
    placeholderData: keepPreviousData,
  })

  const usageStatsLoading = summaryLoading

  const {
    data: breakdown,
    isLoading: breakdownLoading,
    isFetching: breakdownFetching,
  } = useQuery({
    queryKey: ['org-usage', 'breakdown', groupBy, dataParams, 'page', 1],
    queryFn: ({ signal }) =>
      apiClient.getOrgUsageBreakdown({
        ...dataParams,
        group_by: groupBy,
        limit: USAGE_TABLE_PAGE_SIZE,
        offset: 0,
      }, signal),
    enabled: !showWorkspaceComposite,
    ...usageQueryDefaults,
    placeholderData: (previousData, previousQuery) => {
      if (!previousQuery || previousQuery.queryKey[2] !== groupBy) return undefined
      return previousData
    },
  })

  const firstPageFits = Boolean(breakdown) && !breakdown?.truncated_at_limit
  const {
    data: laterBreakdown,
    isLoading: laterBreakdownLoading,
    isFetching: laterBreakdownFetching,
  } = useQuery({
    queryKey: ['org-usage', 'breakdown', groupBy, dataParams, 'page', tablePage],
    queryFn: ({ signal }) =>
      apiClient.getOrgUsageBreakdown({
        ...dataParams,
        group_by: groupBy,
        limit: USAGE_TABLE_PAGE_SIZE,
        offset: (tablePage - 1) * USAGE_TABLE_PAGE_SIZE,
      }, signal),
    enabled: !showWorkspaceComposite && tablePage > 1 && !firstPageFits,
    ...usageQueryDefaults,
  })

  const compositeDepth = tablePage * USAGE_TABLE_PAGE_SIZE
  const {
    data: importBreakdown,
    isLoading: importBreakdownLoading,
    isFetching: importBreakdownFetching,
  } = useQuery({
    queryKey: ['org-usage', 'breakdown', 'call_import', dataParams, compositeDepth],
    queryFn: ({ signal }) =>
      fetchUsageGroupRows(
        { ...dataParams, group_by: 'call_import' },
        compositeDepth,
        signal,
      ),
    enabled: showWorkspaceComposite,
    ...usageQueryDefaults,
  })

  const {
    data: resourceBreakdown,
    isLoading: resourceBreakdownLoading,
    isFetching: resourceBreakdownFetching,
  } = useQuery({
    queryKey: ['org-usage', 'breakdown', 'resource', dataParams, compositeDepth],
    queryFn: ({ signal }) =>
      fetchUsageGroupRows(
        { ...dataParams, group_by: 'resource' },
        compositeDepth,
        signal,
      ),
    enabled: showWorkspaceComposite,
    ...usageQueryDefaults,
  })

  const { data: filterOptions, isFetching: filtersLoading } = useQuery({
    queryKey: ['org-usage', 'filters', scopeParams],
    queryFn: ({ signal }) => apiClient.getOrgUsageFilters(scopeParams, signal),
    ...usageQueryDefaults,
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

  const activeBreakdown =
    !showWorkspaceComposite && tablePage > 1 && !firstPageFits
      ? laterBreakdown
      : breakdown
  const breakdownMatchesLevel = activeBreakdown?.group_by === groupBy
  const rawRows = useMemo((): BreakdownRow[] => {
    if (!activeBreakdown || !breakdownMatchesLevel) return []
    return activeBreakdown.rows as BreakdownRow[]
  }, [activeBreakdown, breakdownMatchesLevel])

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
  const { rows, hasNextPage } = useMemo(() => {
    if (showWorkspaceComposite) {
      const importReady = importBreakdown?.group_by === 'call_import'
      const resourceReady = resourceBreakdown?.group_by === 'resource'
      if (!importReady && !resourceReady) {
        return { rows: [] as TableRow[], hasNextPage: false }
      }
      const streamsTruncated = Boolean(
        importBreakdown?.truncated_at_limit || resourceBreakdown?.truncated_at_limit,
      )
      const merged = buildWorkspaceCompositeRows(
        importReady
          ? filterTableRows(importBreakdown.rows as BreakdownRow[], usageKind, scopeActive)
          : [],
        resourceReady
          ? filterTableRows(resourceBreakdown.rows as BreakdownRow[], usageKind, scopeActive)
          : [],
        mergeOptions,
        padMissingRows && !streamsTruncated,
      )
      const start = (tablePage - 1) * USAGE_TABLE_PAGE_SIZE
      return {
        rows: merged.slice(start, start + USAGE_TABLE_PAGE_SIZE),
        hasNextPage:
          merged.length > start + USAGE_TABLE_PAGE_SIZE || streamsTruncated,
      }
    }
    const decorated = mergeDrillRows(
      groupBy,
      filteredRawRows,
      mergeOptions,
      padMissingRows && firstPageFits,
    )
    if (firstPageFits) {
      const start = (tablePage - 1) * USAGE_TABLE_PAGE_SIZE
      return {
        rows: decorated.slice(start, start + USAGE_TABLE_PAGE_SIZE),
        hasNextPage: decorated.length > start + USAGE_TABLE_PAGE_SIZE,
      }
    }
    return {
      rows: decorated.slice(0, USAGE_TABLE_PAGE_SIZE),
      hasNextPage: Boolean(activeBreakdown?.truncated_at_limit),
    }
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
    tablePage,
    firstPageFits,
    activeBreakdown,
  ])

  const breakdownStale =
    !showWorkspaceComposite && breakdownFetching && !breakdownMatchesLevel
  const tableLoading = showWorkspaceComposite
    ? (importBreakdownLoading || resourceBreakdownLoading) &&
      !importBreakdown &&
      !resourceBreakdown
    : tablePage > 1 && !firstPageFits
      ? laterBreakdownLoading && !laterBreakdown
      : breakdownLoading && !breakdown
  const tableFetching = showWorkspaceComposite
    ? importBreakdownFetching || resourceBreakdownFetching
    : tablePage > 1 && !firstPageFits
      ? laterBreakdownFetching
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

  const workspaceLabel =
    filterOptions?.workspaces?.find((w) => idKey(w.id) === idKey(workspaceId))?.name
  const callImportLabel =
    filterOptions?.call_imports?.find((c) => idKey(c.id) === idKey(callImportId))?.label
  const evaluationLabel =
    filterOptions?.resources?.find((r) => idKey(r.id) === idKey(evaluationId))?.label ||
    filterOptions?.evaluations?.find((e) => idKey(e.id) === idKey(evaluationId))?.label

  const productSectionLabel =
    filterOptions?.product_sections?.find((s) => s.id === productSection)?.label

  const modelLabelContext = useMemo((): UsageModelLabelContext | undefined => {
    if (!model) return undefined
    const fromBreakdown = breakdown?.rows?.find((row) => row.model === model)
    if (fromBreakdown) return fromBreakdown
    if (drilledModelContext) return drilledModelContext
    if (usageKind) return { usage_kind: usageKind }
    return undefined
  }, [breakdown?.rows, drilledModelContext, model, usageKind])

  const modelDisplayLabel = model
    ? usageModelDisplayLabel(model, modelLabelContext)
    : ''

  const scopeSubtitle = model
    ? modelDisplayLabel
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
    ...(model ? [{ label: modelDisplayLabel }] : []),
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
      setDrilledModelContext({
        total_tokens: row.total_tokens,
        audio_seconds: row.audio_seconds,
        tts_characters: row.tts_characters,
        call_count: row.call_count,
        usage_kind: row.usage_kind,
      })
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
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <div
          className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5 text-xs font-medium"
          role="group"
          aria-label="Display currency"
        >
          {(['USD', 'INR'] as const).map((currency) => (
            <button
              key={currency}
              type="button"
              title={currency === 'INR' ? fxRateHint : undefined}
              onClick={() => {
                setDisplayCurrency(currency)
                setUsageDisplayCurrency(currency)
              }}
              className={`rounded-md px-2.5 py-1 transition-colors ${
                displayCurrency === currency
                  ? 'bg-gray-900 text-white'
                  : 'text-gray-600 hover:bg-gray-50'
              }`}
            >
              {currency}
            </button>
          ))}
        </div>
        {showCostBreakdown ? (
          <button
            type="button"
            onClick={() => setCostBreakdownOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 shadow-sm transition-colors hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900"
            title={formatCostExact(estimatedTotalCost)}
          >
            <CircleDollarSign className="h-4 w-4 shrink-0 text-gray-500" />
            <span className="whitespace-nowrap">Cost breakdown</span>
          </button>
        ) : null}
        {summary?.last_updated_at ? (
          <p className="text-[11px] text-gray-400 whitespace-nowrap">
            Updated {new Date(summary.last_updated_at).toLocaleString()}
          </p>
        ) : null}
      </div>

      {summaryError ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Could not load usage data
          {summaryQueryError instanceof Error && summaryQueryError.message
            ? `: ${summaryQueryError.message}`
            : '.'}{' '}
          Try refreshing the page.
        </div>
      ) : null}

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
          <StatCard
            label="Input tokens"
            display={formatCompactCount(totals?.prompt_tokens || 0)}
            exact={formatExactCount(totals?.prompt_tokens || 0)}
            loading={usageStatsLoading}
          />
          <StatCard
            label="Output tokens"
            display={formatCompactCount(totals?.completion_tokens || 0)}
            exact={formatExactCount(totals?.completion_tokens || 0)}
            loading={usageStatsLoading}
          />
          <StatCard
            label="Total tokens"
            display={formatCompactCount(totals?.total_tokens || 0)}
            exact={formatExactCount(totals?.total_tokens || 0)}
            loading={usageStatsLoading}
          />
          <StatCard
            label="LLM calls"
            display={formatCompactCount(totals?.call_count || 0)}
            exact={formatExactCount(totals?.call_count || 0)}
            loading={usageStatsLoading}
          />
          {showAudio ? (
            <StatCard
              label="STT audio"
              display={formatAudioDuration(totals?.audio_seconds || 0)}
              exact={formatAudioExact(totals?.audio_seconds || 0)}
              loading={usageStatsLoading}
            />
          ) : null}
          {showTts ? (
            <StatCard
              label="TTS characters"
              display={formatCompactCount(totals?.tts_characters || 0)}
              exact={formatExactCount(totals?.tts_characters || 0)}
              loading={usageStatsLoading}
            />
          ) : null}
          {(totals?.cache_read_tokens || 0) > 0 ? (
            <StatCard
              label="Cache read"
              display={formatCompactCount(totals?.cache_read_tokens || 0)}
              exact={formatExactCount(totals?.cache_read_tokens || 0)}
              loading={usageStatsLoading}
            />
          ) : null}
          {(totals?.cache_creation_tokens || 0) > 0 ? (
            <StatCard
              label="Cache write"
              display={formatCompactCount(totals?.cache_creation_tokens || 0)}
              exact={formatExactCount(totals?.cache_creation_tokens || 0)}
              loading={usageStatsLoading}
            />
          ) : null}
          {(totals?.reasoning_tokens || 0) > 0 ? (
            <StatCard
              label="Reasoning"
              display={formatCompactCount(totals?.reasoning_tokens || 0)}
              exact={formatExactCount(totals?.reasoning_tokens || 0)}
              loading={usageStatsLoading}
            />
          ) : null}
          <StatCard
            label="Estimated cost"
            display={formatCostUsd(estimatedTotalCost)}
            exact={formatCostExact(estimatedTotalCost)}
            loading={usageStatsLoading}
            emphasize
          />
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
        <div className="border-b border-gray-100 px-4 py-3">
          <UsageDrillPath crumbs={drillCrumbs} levelLabel={levelHint} />
        </div>
        <CardBody className="p-0">
          <div
            ref={tableScrollRef}
            className="overflow-x-auto max-h-[min(70vh,640px)] overflow-y-auto custom-scrollbar"
          >
          {tableLoading || breakdownStale ? (
            <div className="flex justify-center py-12">
              <Spinner />
            </div>
          ) : rows.length === 0 && tablePage === 1 ? (
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
                      <td className="px-4 py-3 text-right">
                        <UsageMetricValue
                          display={formatCompactCount(row.call_count)}
                          exact={formatExactCount(row.call_count)}
                        />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <UsageMetricValue
                          display={formatCompactCount(row.prompt_tokens)}
                          exact={formatExactCount(row.prompt_tokens)}
                        />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <UsageMetricValue
                          display={formatCompactCount(row.completion_tokens)}
                          exact={formatExactCount(row.completion_tokens)}
                        />
                      </td>
                      <td className="px-4 py-3 text-right font-medium">
                        <UsageMetricValue
                          display={formatCompactCount(row.total_tokens)}
                          exact={formatExactCount(row.total_tokens)}
                        />
                      </td>
                      <td className="px-4 py-3 text-right text-gray-700">
                        <UsageMetricValue
                          display={formatCostUsd(rowCostUsd(row))}
                          exact={formatCostExact(rowCostUsd(row))}
                        />
                      </td>
                      <td className="px-4 py-3 text-right text-gray-500">
                        {row.audio_seconds ? (
                          <UsageMetricValue
                            display={formatAudioDuration(row.audio_seconds)}
                            exact={formatAudioExact(row.audio_seconds)}
                          />
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-500">
                        {row.tts_characters ? (
                          <UsageMetricValue
                            display={formatCompactCount(row.tts_characters)}
                            exact={formatExactCount(row.tts_characters)}
                          />
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-500">
                        <UsageMetricValue
                          display={formatCompactCount(row.cache_read_tokens)}
                          exact={formatExactCount(row.cache_read_tokens)}
                        />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <UsageTablePager
              page={tablePage}
              hasNext={hasNextPage}
              disabled={tableFetching}
              onPrev={() => setTablePage((page) => Math.max(1, page - 1))}
              onNext={() => setTablePage((page) => page + 1)}
            />
            </div>
          )}
          </div>
        </CardBody>
      </Card>

      <UsageCostBreakdownModal
        isOpen={costBreakdownOpen}
        onClose={() => setCostBreakdownOpen(false)}
        costs={totals?.costs}
        scopeLabel={scopeSubtitle}
        formatCost={formatCostExact}
      />
    </div>
  )
}

const statCardClass = 'border border-gray-200 ring-1 ring-[#fde047]/25 shadow-sm'

function StatCard({
  label,
  display,
  exact,
  loading,
  emphasize = false,
  className = '',
}: {
  label: string
  display: string
  exact: string
  loading?: boolean
  emphasize?: boolean
  className?: string
}) {
  return (
    <Card
      shadow="sm"
      className={`${statCardClass}${emphasize ? ' ring-2 ring-[#facc15]/50 bg-[#fefce8]/40' : ''} w-full ${className}`}
    >
      <CardBody className="p-3">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
        <p
          className={`mt-0.5 text-xl font-semibold ${
            emphasize ? 'text-[#854d0e]' : 'text-gray-900'
          }`}
        >
          {loading ? '—' : <UsageMetricValue display={display} exact={exact} />}
        </p>
      </CardBody>
    </Card>
  )
}

function UsageTablePager({
  page,
  hasNext,
  disabled,
  onPrev,
  onNext,
}: {
  page: number
  hasNext: boolean
  disabled?: boolean
  onPrev: () => void
  onNext: () => void
}) {
  if (page <= 1 && !hasNext) return null
  const buttonClass =
    'inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40'
  return (
    <div className="flex items-center justify-between gap-3 border-t border-gray-100 px-4 py-3">
      <button
        type="button"
        className={buttonClass}
        disabled={disabled || page <= 1}
        onClick={onPrev}
      >
        <ChevronLeft className="h-4 w-4" />
        Previous
      </button>
      <span className="text-sm font-medium text-gray-500">Page {page}</span>
      <button
        type="button"
        className={buttonClass}
        disabled={disabled || !hasNext}
        onClick={onNext}
      >
        Next
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  )
}
