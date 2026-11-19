import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react'
import { apiClient } from '../../../lib/api'
import {
  formatUsageCostExactUsd,
  formatUsageCostUsd,
  type UsageDisplayCurrency,
} from '../../../lib/usageCurrency'
import { UsageDisplayCurrencyPicker, readUsageDisplayCurrency } from './UsageDisplayCurrencyPicker'
import { itemsOf } from '../../../lib/safeData'
import type {
  CallImportMetricAggregate,
  DashboardOpsScoreDay,
  EvaluatorResultRow,
  EvaluatorResultsAgentSummary,
  EvaluatorResultsDashboardOpsResponse,
} from '../../../types/api'
import type { DashboardDrillCall } from './resultsDashboardSample'
import { usageFromEvaluatorCallData } from './evaluatorDrillUsage'
import {
  LAYER_LLM,
  MERGED_TOOLS_VIEWS,
  formatChartNumber,
  formatDuration,
  scoreTrendForWindow,
  mergedToolsDetail,
  resolveToolAgentFocusId,
  totalToolErrors,
  toolFacts,
  type ToolInsightMode,
  usageDetail,
  usageFacts,
  usageHasS2S,
} from './resultsDashboardSeries'
import { DrillChartPanel, DrillTrendChart } from './resultsDashboardDrillCharts'
import { isGoldenMetric, type MetricRow } from '../../simulations/simulationMetricScope'
import type { ListEvaluatorResultsParams } from '../../../types/api'
import type { RunListBase } from './resultsDashboardInsightDrill'
import {
  calendarDayToSinceUntil,
  formatChartDayLabel,
  formatDashboardWindowLabel,
  intersectSinceUntil,
} from './resultsDateRange'
import { getUsageTimezone } from '../../usage/usageTimezone'
import { evaluatorResultOpenId } from './ResultsRunDetailDrawer'

export type { RunListBase } from './resultsDashboardInsightDrill'

const PAGE_SIZE = 20

function formatCallTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function formatCostCell(costUsd: number, currency: UsageDisplayCurrency, inrRate: number): string {
  if (!costUsd) return '—'
  return formatUsageCostExactUsd(costUsd, currency, inrRate)
}

export function PaginatedRunsTable({
  base,
  filterAgentId,
  filterScenarioId,
  metricId,
  scoreMetricId,
  title = 'Runs',
  onOpenResult,
  callsByResultId,
  inrRate = 95,
  displayCurrency,
  rich = false,
  usageModel,
  usageRole,
  toolUse,
  toolProduct,
  toolFailuresOnly,
  hasToolCalls,
}: {
  base: RunListBase
  filterAgentId?: string
  filterScenarioId?: string
  metricId?: string
  /** When set, list rows show this metric's score (still paginates all runs in the window). */
  scoreMetricId?: string
  title?: string
  onOpenResult: (resultId: string) => void
  callsByResultId?: DashboardDrillCall[]
  inrRate?: number
  displayCurrency?: UsageDisplayCurrency
  rich?: boolean
  /** When set, paginate runs that consumed this model and show that model's tokens/cost. */
  usageModel?: string
  /** When set, show tokens/cost for this usage role (agent | simulator | judge). */
  usageRole?: string
  toolUse?: string
  toolProduct?: string
  toolFailuresOnly?: boolean
  hasToolCalls?: boolean
}) {
  const currency = displayCurrency ?? readUsageDisplayCurrency()
  const [page, setPage] = useState(0)
  const runScopeKey = useMemo(
    () =>
      JSON.stringify({
        agentId: filterAgentId || base.agentId || undefined,
        suiteId: base.suiteId || undefined,
        scenarioId: filterScenarioId || base.scenarioId || undefined,
        since: base.since,
        until: base.until,
        playground: base.playground,
        metricId: metricId || undefined,
        usageModel: usageModel || undefined,
        usageRole: usageRole || undefined,
        toolUse: toolUse || undefined,
        toolProduct: toolProduct || undefined,
        toolFailuresOnly: toolFailuresOnly || undefined,
        hasToolCalls: hasToolCalls || undefined,
        sampleOn: base.sampleOn,
      }),
    [base, filterAgentId, filterScenarioId, metricId, usageModel, usageRole, toolUse, toolProduct, toolFailuresOnly, hasToolCalls],
  )
  const listParams = useMemo(
    () => ({
      agentId: filterAgentId || base.agentId || undefined,
      suiteId: base.suiteId || undefined,
      scenarioId: filterScenarioId || base.scenarioId || undefined,
      since: base.since,
      until: base.until,
      playground: base.playground,
      metricId: metricId || undefined,
      usageModel: usageModel || undefined,
      toolUse: toolUse || undefined,
      toolProduct: toolProduct || undefined,
      toolFailuresOnly: toolFailuresOnly || undefined,
      hasToolCalls: hasToolCalls || undefined,
      skip: page * PAGE_SIZE,
      limit: PAGE_SIZE,
    }),
    [runScopeKey, page, base, filterAgentId, filterScenarioId, metricId, usageModel, usageRole, toolUse, toolProduct, toolFailuresOnly, hasToolCalls],
  )
  const { data, isLoading } = useQuery({
    queryKey: ['evaluator-results-drill-runs', listParams, metricId, usageModel, usageRole],
    queryFn: () => apiClient.listEvaluatorResults(listParams as ListEvaluatorResultsParams),
    enabled: !base.sampleOn,
    staleTime: 60_000,
  })
  const sampleFiltered = useMemo(() => {
    let rows = base.sampleRows
    if (filterAgentId) rows = rows.filter((row) => row.agent_id === filterAgentId)
    if (filterScenarioId) rows = rows.filter((row) => row.scenario?.id === filterScenarioId)
    if (metricId) rows = rows.filter((row) => row.metric_scores?.[metricId])
    return rows
  }, [base.sampleRows, filterAgentId, filterScenarioId, metricId])
  const items = base.sampleOn ? sampleFiltered.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE) : itemsOf<EvaluatorResultRow>(data)
  const total = base.sampleOn ? sampleFiltered.length : data?.total ?? 0
  const pages = total ? Math.max(1, Math.ceil(total / PAGE_SIZE)) : 0
  const callLookup = useMemo(() => {
    const map = new Map<string, DashboardDrillCall>()
    for (const call of callsByResultId ?? []) {
      if (call.resultId) map.set(call.resultId, call)
    }
    return map
  }, [callsByResultId])
  const useRich = rich || callLookup.size > 0
  useEffect(() => {
    setPage(0)
  }, [runScopeKey])

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        {title ? <h3 className="text-sm font-semibold text-gray-900">{title}</h3> : <span className="sr-only">Runs</span>}
        <div className="ml-auto flex shrink-0 items-center gap-2 text-xs text-gray-500">
          <button
            type="button"
            disabled={page <= 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="rounded border border-gray-200 p-1 disabled:opacity-30"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span>
            {total ? page + 1 : 0} / {pages}
          </span>
          <button
            type="button"
            disabled={page >= pages - 1}
            onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
            className="rounded border border-gray-200 p-1 disabled:opacity-30"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
      {isLoading && !base.sampleOn ? (
        <p className="mt-3 text-sm text-gray-400">Loading runs…</p>
      ) : useRich ? (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
              <tr>
                <th className="pb-2 pr-3">When</th>
                <th className="pb-2 pr-3">Run</th>
                <th className="pb-2 pr-3">Agent</th>
                <th className="pb-2 pr-3 text-right">Duration</th>
                <th className="pb-2 pr-3 text-right">Tokens</th>
                <th className="pb-2 pr-3 text-right">Cost</th>
                <th className="pb-2 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((row) => {
                const call = callLookup.get(row.result_id || row.id)
                const inlineUsage = usageFromEvaluatorCallData(
                  row.call_data,
                  row.provider_platform,
                  usageModel,
                  usageRole,
                )
                const prefetchSlice = usageModel
                  ? call?.usageByModel?.[usageModel]
                  ?? Object.entries(call?.usageByModel ?? {}).find(
                    ([name]) => name.trim().toLowerCase() === usageModel.trim().toLowerCase(),
                  )?.[1]
                  : undefined
                const tokens = usageModel
                  ? (prefetchSlice?.tokens ?? inlineUsage.tokens)
                  : (call?.tokens ?? inlineUsage.tokens)
                const costUsd = usageModel
                  ? (prefetchSlice?.costUsd ?? inlineUsage.costUsd)
                  : (call?.costUsd ?? inlineUsage.costUsd)
                return (
                  <tr key={row.id} className="group">
                    <td className="py-2.5 pr-3 text-xs text-gray-500">
                      {usageModel && typeof row.call_data?.usage_on === 'string'
                        ? formatChartDayLabel(row.call_data.usage_on, false)
                        : formatCallTime(row.timestamp)}
                    </td>
                    <td className="py-2.5 pr-3">
                      <button
                        type="button"
                        onClick={() => onOpenResult(evaluatorResultOpenId(row))}
                        className="max-w-[12rem] truncate text-left font-medium text-gray-900 group-hover:text-primary-800"
                      >
                        {row.name || row.result_id}
                      </button>
                    </td>
                    <td className="py-2.5 pr-3 text-gray-700">{call?.agent ?? row.agent?.name ?? '—'}</td>
                    <td className="py-2.5 pr-3 text-right tabular-nums text-gray-600">
                      {formatDuration(call?.durationSeconds ?? row.duration_seconds ?? null)}
                    </td>
                    <td className="py-2.5 pr-3 text-right tabular-nums text-gray-600">
                      {tokens ? tokens.toLocaleString() : '—'}
                    </td>
                    <td className="py-2.5 pr-3 text-right text-xs tabular-nums text-gray-600">
                      {costUsd ? formatCostCell(costUsd, currency, inrRate) : '—'}
                    </td>
                    <td className="py-2.5 text-right text-xs capitalize text-gray-500">{row.status}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {!items.length && (
            <p className="py-4 text-sm text-gray-400">
              {usageModel
                ? 'No runs attributed to this model in the current filter. Ledger spend may be judge/simulator usage matched by evaluator, agent, and run day.'
                : 'No runs in this slice.'}
            </p>
          )}
        </div>
      ) : (
        <ul className="mt-3 divide-y divide-gray-100">
          {items.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                onClick={() => onOpenResult(evaluatorResultOpenId(row))}
                className="flex w-full items-center justify-between gap-3 py-2 text-left text-sm hover:text-primary-800"
              >
                <span className="min-w-0 truncate font-medium text-gray-900">{row.name || row.result_id}</span>
                <span className="shrink-0 text-xs text-gray-500">
                  {scoreMetricId && row.metric_scores?.[scoreMetricId] != null
                    ? `${String(row.metric_scores[scoreMetricId]?.value ?? row.metric_scores[scoreMetricId])} · `
                    : ''}
                  {new Date(row.timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric' })}
                  {row.duration_seconds != null ? ` · ${Math.round(row.duration_seconds)}s` : ''}
                </span>
              </button>
            </li>
          ))}
          {!items.length && <li className="py-4 text-sm text-gray-400">No runs in this slice.</li>}
        </ul>
      )}
    </section>
  )
}

/** Paginate pre-loaded drill calls (e.g. model cost focus) when API has no model filter. */
export function PaginatedCallRunsTable({
  calls,
  title = 'Runs',
  onOpenResult,
  inrRate = 95,
  displayCurrency,
}: {
  calls: DashboardDrillCall[]
  title?: string
  onOpenResult: (resultId: string) => void
  inrRate?: number
  displayCurrency?: UsageDisplayCurrency
}) {
  const currency = displayCurrency ?? readUsageDisplayCurrency()
  const [page, setPage] = useState(0)
  const sorted = useMemo(
    () => [...calls].sort((a, b) => b.at.localeCompare(a.at)),
    [calls],
  )
  const total = sorted.length
  const pages = total ? Math.max(1, Math.ceil(total / PAGE_SIZE)) : 0
  const pageCalls = sorted.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE)
  const callsScopeKey = useMemo(
    () => `${calls.length}:${calls[0]?.resultId ?? ''}:${calls[calls.length - 1]?.resultId ?? ''}`,
    [calls],
  )
  useEffect(() => {
    setPage(0)
  }, [callsScopeKey])

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        {title ? <h3 className="text-sm font-semibold text-gray-900">{title}</h3> : <span className="sr-only">Runs</span>}
        <div className="ml-auto flex shrink-0 items-center gap-2 text-xs text-gray-500">
          <button
            type="button"
            disabled={page <= 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="rounded border border-gray-200 p-1 disabled:opacity-30"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span>
            {total ? page + 1 : 0} / {pages}
          </span>
          <button
            type="button"
            disabled={page >= pages - 1}
            onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
            className="rounded border border-gray-200 p-1 disabled:opacity-30"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[36rem] text-left text-sm">
          <thead className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
            <tr>
              <th className="pb-2 pr-3">When</th>
              <th className="pb-2 pr-3">Run</th>
              <th className="pb-2 pr-3">Agent</th>
              <th className="pb-2 pr-3 text-right">Duration</th>
              <th className="pb-2 pr-3 text-right">Cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {pageCalls.map((call) => (
              <tr key={`${call.at}-${call.resultId}`} className="group">
                <td className="py-2.5 pr-3 text-xs text-gray-500">{formatCallTime(call.at)}</td>
                <td className="py-2.5 pr-3">
                  <button
                    type="button"
                    onClick={() => call.resultId && onOpenResult(call.resultId)}
                    className="max-w-[14rem] truncate text-left font-medium text-gray-900 group-hover:text-primary-800"
                  >
                    {call.title || call.resultId || 'Run'}
                  </button>
                </td>
                <td className="py-2.5 pr-3 text-gray-700">{call.agent}</td>
                <td className="py-2.5 pr-3 text-right tabular-nums text-gray-600">
                  {formatDuration(call.durationSeconds)}
                </td>
                <td className="py-2.5 text-right text-xs tabular-nums text-gray-600">
                  {call.costUsd ? formatCostCell(call.costUsd, currency, inrRate) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!pageCalls.length && <p className="py-4 text-sm text-gray-400">No runs in this slice.</p>}
      </div>
    </section>
  )
}

function UsageModelDrillLeaf({
  model,
  ops,
  calls,
  runListBase,
  inrRate,
  displayCurrency,
  onBack,
  onOpenResult,
}: {
  model: string
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  calls: DashboardDrillCall[]
  runListBase: RunListBase
  inrRate: number
  displayCurrency: UsageDisplayCurrency
  onBack: () => void
  onOpenResult: (resultId: string) => void
}) {
  const layer = ops?.model_layers.find((row) => row.model === model)
  const modelDays = (ops?.cost_by_model_day ?? []).filter((row) => row.model === model)
  const modelSpendUsd = modelDays.reduce((sum, row) => sum + row.cost_usd, 0)
  const runCountParams = useMemo(
    () => ({
      agentId: runListBase.agentId || undefined,
      suiteId: runListBase.suiteId || undefined,
      scenarioId: runListBase.scenarioId || undefined,
      since: runListBase.since,
      until: runListBase.until,
      playground: runListBase.playground,
      usageModel: model,
      skip: 0,
      limit: 1,
    }),
    [runListBase, model],
  )
  const { data: runCountData } = useQuery({
    queryKey: ['evaluator-results-drill-runs-count', runCountParams],
    queryFn: () => apiClient.listEvaluatorResults(runCountParams as ListEvaluatorResultsParams),
    staleTime: 60_000,
  })
  const attributedRunCount = runCountData?.total ?? 0
  const attributedSpend = runCountData?.usage_cost_usd
  const headlineUsd = attributedSpend != null ? attributedSpend : modelSpendUsd
  const spendHeadline = formatUsageCostUsd(headlineUsd, displayCurrency, inrRate)
  const unit =
    layer?.usd_per_minute != null
      ? `$${layer.usd_per_minute}/min`
      : layer?.usd_per_million_tokens != null
        ? `$${layer.usd_per_million_tokens}/1M tok`
        : null

  return (
    <div className="space-y-4">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900">
        <ArrowLeft className="h-4 w-4" />
        Back
      </button>
      <header className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">Model</p>
        <h2 className="text-lg font-semibold text-gray-900">{model}</h2>
        <p className="mt-1 text-sm text-gray-500">
          {layer?.usage_kind ? layer.usage_kind.toUpperCase() : 'Model'}
          {unit ? ` · ${unit}` : ''}
          {' · '}Pre-prod runs in the current filter
        </p>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-gray-400">Spend in window</dt>
            <dd className="font-semibold tabular-nums text-gray-900" title={formatUsageCostExactUsd(headlineUsd, displayCurrency, inrRate)}>
              {spendHeadline}
            </dd>
            <p className="mt-0.5 text-[11px] text-gray-400">Total attributed to the runs below, across every page</p>
          </div>
          <div>
            <dt className="text-xs text-gray-400">Attributed runs</dt>
            <dd className="font-semibold text-gray-900">
              {attributedRunCount.toLocaleString()}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-gray-400">Model layer</dt>
            <dd className="font-semibold text-gray-900">{layer?.usage_kind?.toUpperCase() ?? '—'}</dd>
          </div>
        </dl>
      </header>
      {modelDays.length > 0 && (
        <DrillChartPanel
          model={{
            headline: spendHeadline,
            caption: 'Spend over time',
            data: modelDays.map((row) => ({ day: row.day, spend: row.cost_usd })),
            series: [{ key: 'spend', color: LAYER_LLM }],
          }}
          display="area"
          valueFormat="currency"
          inrRate={inrRate}
          displayCurrency={displayCurrency}
        />
      )}
      <PaginatedRunsTable
        base={runListBase}
        title="Runs using this model"
        usageModel={model}
        onOpenResult={onOpenResult}
        callsByResultId={calls}
        inrRate={inrRate}
        displayCurrency={displayCurrency}
        rich
      />
    </div>
  )
}

export function UsageWidgetDetail({
  ops,
  calls,
  runListBase,
  dateRange,
  allTime,
  onBack,
  onOpenResult,
}: {
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  calls: DashboardDrillCall[]
  runListBase: RunListBase
  dateRange: { start: string; end: string } | null
  allTime?: boolean
  onBack: () => void
  onOpenResult: (resultId: string) => void
}) {
  const windowLabel = formatDashboardWindowLabel(dateRange, allTime)
  const views = [
    { id: 'stt', label: 'STT models' },
    { id: 'tts', label: 'TTS models' },
    { id: 'llm', label: 'LLM models' },
    ...(usageHasS2S(ops) ? [{ id: 's2s', label: 'S2S models' }] : []),
    { id: 'price_minute', label: 'Price / minute' },
    { id: 'price_million', label: 'Price / 1M tokens' },
  ]
  const [viewId, setViewId] = useState(views[0]?.id ?? 'stt')
  const [focusModel, setFocusModel] = useState<string | null>(null)
  const activeId = views.some((view) => view.id === viewId) ? viewId : views[0]?.id
  const chart = usageDetail(ops, activeId ?? 'stt', focusModel)
  const spend = usageFacts(ops)
  const [displayCurrency, setDisplayCurrency] = useState<UsageDisplayCurrency>(readUsageDisplayCurrency)
  const { data: fxRate } = useQuery({
    queryKey: ['org-usage', 'fx-rate'],
    queryFn: () => apiClient.getOrgUsageFxRate(),
    staleTime: 60 * 60 * 1000,
  })
  const inrRate = fxRate?.rate ?? 95
  const totalUsd = (ops?.cost_by_agent ?? []).reduce((sum, row) => sum + row.total_usd, 0)
  const spendHeadline = formatUsageCostUsd(totalUsd, displayCurrency, inrRate)

  if (focusModel) {
    return (
      <UsageModelDrillLeaf
        model={focusModel}
        ops={ops}
        calls={calls}
        runListBase={runListBase}
        inrRate={inrRate}
        displayCurrency={displayCurrency}
        onBack={() => setFocusModel(null)}
        onOpenResult={onOpenResult}
      />
    )
  }

  return (
    <div className="space-y-4">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900">
        <ArrowLeft className="h-4 w-4" />
        Back to dashboard
      </button>
      <header className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">Usage</p>
            <h2 className="text-lg font-semibold tabular-nums text-gray-900" title={formatUsageCostExactUsd(totalUsd, displayCurrency, inrRate)}>
              {spendHeadline}
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              {windowLabel} · simulated and live pre-prod runs only
            </p>
          </div>
          <UsageDisplayCurrencyPicker compact value={displayCurrency} onChange={setDisplayCurrency} />
        </div>
        <dl className="mt-4 grid grid-cols-3 gap-2 text-sm">
          <MotionStat label="Highest spend" value={spend.highest} />
          <MotionStat label="Most used" value={spend.most} />
          <MotionStat label="Least used" value={spend.least} />
        </dl>
      </header>
      <div className="flex flex-wrap gap-1 rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
        {views.map((view) => (
          <button
            key={view.id}
            type="button"
            onClick={() => setViewId(view.id)}
            className={`rounded-md border px-2.5 py-1 text-xs font-medium ${activeId === view.id ? 'border-primary-200 bg-primary-50 text-primary-800' : 'border-transparent text-gray-600 hover:bg-gray-50'}`}
          >
            {view.label}
          </button>
        ))}
      </div>
      <DrillChartPanel
        model={chart}
        display={chart.data[0] && 'day' in chart.data[0] ? 'area' : 'bar'}
        valueFormat="currency"
        inrRate={inrRate}
        displayCurrency={displayCurrency}
        onCategory={(name) => {
          const usesDayAxis = chart.data[0] != null && 'day' in chart.data[0]
          const priceView = activeId === 'price_minute' || activeId === 'price_million'
          if (usesDayAxis || priceView) return
          const layers = ops?.model_layers ?? []
          const exact = layers.find((layer) => layer.model === name)
          if (exact) {
            setFocusModel(exact.model)
            return
          }
          const needle = name.replace(/-+$/, '').trim().toLowerCase()
          const fuzzy = layers.find(
            (layer) =>
              layer.model.toLowerCase() === needle
              || layer.model.toLowerCase().startsWith(needle),
          )
          if (fuzzy) setFocusModel(fuzzy.model)
        }}
      />
    </div>
  )
}

function MotionStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-gray-400">{label}</dt>
      <dd className="font-medium text-gray-900">{value}</dd>
    </div>
  )
}

type ToolDrillLeaf =
  | { kind: 'named_tool'; useKind: 'use_case' | 'product'; name: string; dayKey?: string }
  | { kind: 'agent_runs'; agentId: string; agentName: string; dayKey?: string }

function toolsRunListBase(
  base: RunListBase,
  dayKey: string | undefined,
): RunListBase {
  if (!dayKey) return base
  const tz = base.chartTimeZone || getUsageTimezone()
  const dayBounds = calendarDayToSinceUntil(dayKey, tz)
  const bounds = intersectSinceUntil(dayBounds, { since: base.since, until: base.until })
  return { ...base, since: bounds.since, until: bounds.until }
}

function DrillFocusBar({
  label,
  onClear,
}: {
  label: string
  onClear: () => void
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-sm text-primary-900">
      <span>
        Focused on <span className="font-semibold">{label}</span>
      </span>
      <button
        type="button"
        onClick={onClear}
        className="rounded-md border border-primary-300 bg-white px-2.5 py-1 text-xs font-semibold text-primary-800 hover:bg-primary-100"
      >
        Clear focus
      </button>
    </div>
  )
}

export function ToolsMergedDetail({
  ops,
  calls: _calls,
  runListBase,
  dateRange,
  allTime,
  onBack,
  onOpenResult,
}: {
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  calls: DashboardDrillCall[]
  runListBase: RunListBase
  dateRange: { start: string; end: string } | null
  allTime?: boolean
  onBack: () => void
  onOpenResult: (resultId: string) => void
}) {
  const [viewId, setViewId] = useState<(typeof MERGED_TOOLS_VIEWS)[number]['id']>('over_time')
  const [insightMode, setInsightMode] = useState<ToolInsightMode>('calls')
  const [focus, setFocus] = useState<string | null>(null)
  /** Failures → By agent keeps agent selection separate from tool-bar clicks. */
  const [agentFocus, setAgentFocus] = useState<string | null>(null)
  const [drillLeaf, setDrillLeaf] = useState<ToolDrillLeaf | null>(null)
  const chartFocus = viewId === 'by_agent' && insightMode === 'errors' ? agentFocus : focus
  const chart = mergedToolsDetail(ops, viewId, chartFocus, insightMode)
  const agentFocusResolved =
    viewId === 'by_agent' && insightMode === 'errors' && agentFocus
      ? resolveToolAgentFocusId(ops, agentFocus)
      : null
  const products = toolFacts(ops)
  const totalErrors = totalToolErrors(ops)

  const openAgentToolRuns = (agentName: string, dayKey?: string) => {
    const agentId = resolveToolAgentFocusId(ops, agentName)
    if (!agentId) {
      setDrillLeaf({ kind: 'named_tool', useKind: 'product', name: agentName, dayKey })
      return
    }
    setDrillLeaf({ kind: 'agent_runs', agentId, agentName, dayKey })
  }

  if (drillLeaf) {
    const title =
      drillLeaf.kind === 'named_tool'
        ? drillLeaf.name
        : drillLeaf.dayKey
          ? `${drillLeaf.agentName} · ${formatChartDayLabel(drillLeaf.dayKey, false)}`
          : drillLeaf.agentName
    return (
      <div className="space-y-4">
        <button type="button" onClick={() => setDrillLeaf(null)} className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900">
          <ArrowLeft className="h-4 w-4" />
          Back
        </button>
        <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
        <p className="text-sm text-gray-500">
          {insightMode === 'errors' ? 'Runs with tool failures in this slice' : 'Pre-prod runs where production tools were invoked'}
        </p>
        <PaginatedRunsTable
          base={toolsRunListBase(runListBase, drillLeaf.dayKey)}
          filterAgentId={
            drillLeaf.kind === 'agent_runs'
              ? drillLeaf.agentId
              : agentFocusResolved ?? undefined
          }
          toolUse={drillLeaf.kind === 'named_tool' && drillLeaf.useKind === 'use_case' ? drillLeaf.name : undefined}
          toolProduct={drillLeaf.kind === 'named_tool' && drillLeaf.useKind === 'product' ? drillLeaf.name : undefined}
          hasToolCalls={drillLeaf.kind === 'agent_runs'}
          toolFailuresOnly={
            insightMode === 'errors'
            && (drillLeaf.kind === 'named_tool' || drillLeaf.kind === 'agent_runs')
          }
          title={insightMode === 'errors' ? 'Runs with tool failures' : 'Runs with tool calls'}
          onOpenResult={onOpenResult}
          rich
        />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900">
        <ArrowLeft className="h-4 w-4" />
        Back to dashboard
      </button>
      <header className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-gray-900">Tools</h2>
        <p className="text-sm text-gray-500">
          Tool calls and products · {formatDashboardWindowLabel(dateRange, allTime)}
        </p>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
          <MotionStat label="Most used" value={products.most} />
          <MotionStat label="Least used" value={products.least} />
          <MotionStat label="Calls with no tools" value={products.empty} />
          <MotionStat label="Tool failures" value={totalErrors.toLocaleString()} />
        </dl>
      </header>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex flex-wrap gap-1">
          <div className="mr-2 flex items-center rounded-lg border border-gray-200 bg-gray-50 p-0.5">
            {(['calls', 'errors'] as ToolInsightMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => {
                  setInsightMode(mode)
                  setFocus(null)
                  setAgentFocus(null)
                  setDrillLeaf(null)
                }}
                className={`rounded-md border px-2.5 py-1 text-xs font-medium ${insightMode === mode
                  ? 'border-primary-200 bg-white text-primary-800 shadow-sm'
                  : 'border-transparent text-gray-600'
                  }`}
              >
                {mode === 'calls' ? 'Calls' : 'Failures'}
              </button>
            ))}
          </div>
          {MERGED_TOOLS_VIEWS.map((view) => (
            <button
              key={view.id}
              type="button"
              onClick={() => {
                setViewId(view.id)
                setFocus(null)
                setAgentFocus(null)
              }}
              className={`rounded-md border px-2.5 py-1 text-xs font-medium ${viewId === view.id ? 'border-primary-200 bg-primary-50 text-primary-800' : 'border-transparent text-gray-600'}`}
            >
              {view.label}
            </button>
          ))}
        </div>
      </div>
      {(focus || agentFocus) && (
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => {
              setFocus(null)
              setAgentFocus(null)
            }}
            className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900"
          >
            <ArrowLeft className="h-4 w-4" />
            {viewId === 'by_agent' || viewId === 'per_call' ? 'All agents' : 'Show full chart'}
          </button>
          {agentFocus ? (
            <DrillFocusBar label={agentFocus} onClear={() => setAgentFocus(null)} />
          ) : focus ? (
            <DrillFocusBar label={focus} onClear={() => setFocus(null)} />
          ) : null}
        </div>
      )}
      <DrillChartPanel
        model={
          agentFocus
            ? {
              ...chart,
              caption: chart.caption
                ? `${chart.caption} · ${agentFocus}`
                : `Filtered to ${agentFocus}`,
            }
            : focus
              ? {
                ...chart,
                caption: chart.caption
                  ? `${chart.caption} · filtered to ${focus}`
                  : `Filtered to ${focus}`,
              }
              : chart
        }
        display={
          viewId === 'over_time' || (chart.data[0] && 'day' in chart.data[0])
            ? 'line'
            : viewId === 'per_call'
              ? 'area'
              : 'bar'
        }
        onSeriesPoint={(point) => {
          if (viewId !== 'over_time' && viewId !== 'per_call') return
          openAgentToolRuns(point.series, point.sortKey)
        }}
        onCategory={(name) => {
          if (viewId === 'use_cases' || (viewId === 'share' && insightMode === 'errors')) {
            setDrillLeaf({ kind: 'named_tool', useKind: 'use_case', name })
          } else if (viewId === 'share') {
            setDrillLeaf({ kind: 'named_tool', useKind: 'product', name })
          } else if (viewId === 'by_agent' && insightMode === 'errors') {
            if (agentFocusResolved) {
              setDrillLeaf({ kind: 'named_tool', useKind: 'use_case', name })
              return
            }
            setAgentFocus((prev) => (prev === name ? null : name))
          } else if (viewId === 'by_agent' || (viewId === 'per_call' && insightMode === 'calls')) {
            openAgentToolRuns(name)
          }
        }}
      />
    </div>
  )
}

type MetricScopeFilter = 'all' | 'global' | 'local' | 'never'

export function MetricUsageDrill({
  agents,
  metrics,
  catalog,
  scoreDays,
  scenarioRows,
  dateRange,
  allTime,
  results,
  runListBase,
  agentId,
  metricId,
  scenarioId,
  onBack,
  onNavigate,
  onOpenResult,
}: {
  agents: EvaluatorResultsAgentSummary[]
  metrics: CallImportMetricAggregate[]
  catalog: MetricRow[]
  scoreDays: DashboardOpsScoreDay[] | undefined
  scenarioRows: Array<{
    name: string
    count: number
    failed: number
    scenarioId: string
    agentId: string
  }>
  dateRange: { start: string; end: string } | null
  allTime?: boolean
  results: EvaluatorResultRow[]
  runListBase: RunListBase
  agentId?: string
  metricId?: string
  scenarioId?: string
  onBack: () => void
  onNavigate: (next: { agentId?: string; metricId?: string; scenarioId?: string }) => void
  onOpenResult: (resultId: string) => void
}) {
  const windowLabel = formatDashboardWindowLabel(dateRange, allTime)
  const [scope, setScope] = useState<MetricScopeFilter>('all')
  const selectedAgent = agents.find((agent) => agent.agent_id === agentId)
  const catalogById = useMemo(() => new Map(catalog.map((row) => [row.id, row])), [catalog])

  const metricsForAgent = useMemo(() => {
    if (!agentId) return []
    const scored = metrics.filter((metric) => metric.count > 0)
    return scored.filter((metric) => {
      const row = catalogById.get(metric.metric_id)
      if (!row) return true
      if (scope === 'global') return isGoldenMetric(row)
      if (scope === 'local') return !isGoldenMetric(row)
      return true
    })
  }, [agentId, metrics, catalogById, scope])

  const neverMetrics = useMemo(
    () => metrics.filter((metric) => metric.count === 0),
    [metrics],
  )
  const { data: metricMeans } = useQuery({
    queryKey: [
      'scenario-metric-means',
      agentId,
      metricId,
      runListBase.since,
      runListBase.until,
      runListBase.playground,
      runListBase.suiteId,
      runListBase.scenarioId,
    ],
    queryFn: () => apiClient.getEvaluatorResultsDashboardOps({
      agentId,
      suiteId: runListBase.suiteId,
      scenarioId: runListBase.scenarioId,
      since: runListBase.since,
      until: runListBase.until,
      playground: runListBase.playground,
      metricId,
      tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    }),
    enabled: Boolean(agentId && metricId),
    staleTime: 60_000,
  })
  const meanByScenario = useMemo(() => {
    const map = new Map<string, number>()
    for (const row of metricMeans?.scenario_metric_means ?? []) {
      map.set(row.scenario_id, row.mean)
    }
    return map
  }, [metricMeans])

  const scenarios = useMemo(() => {
    if (!agentId || !metricId) return []
    const scoreStats = new Map<string, { sum: number; scored: number }>()
    for (const row of results) {
      if (row.agent_id !== agentId) continue
      const name = row.scenario?.name
      if (!name) continue
      const score = row.metric_scores?.[metricId]
      const value = typeof score?.value === 'number' ? score.value : Number(score?.value)
      if (!Number.isNaN(value) && score) {
        const bucket = scoreStats.get(name) ?? { sum: 0, scored: 0 }
        bucket.sum += value
        bucket.scored += 1
        scoreStats.set(name, bucket)
      }
    }
    const agentSummary = agents.find((item) => item.agent_id === agentId)
    const fromAgent = (agentSummary?.suites ?? []).flatMap((suite) =>
      (suite.scenarios ?? []).map((scenario) => ({
        name: scenario.scenario_name,
        scenarioId: scenario.scenario_id,
        count: scenario.counts.total,
        failed: scenario.counts.failed,
      })),
    )
    const opsForAgent = fromAgent.length > 0
      ? fromAgent
      : scenarioRows.filter((row) => row.agentId === agentId)
    if (opsForAgent.length > 0) {
      return opsForAgent
        .map((row) => {
          const scored = scoreStats.get(row.name)
          return {
            name: row.name,
            scenarioId: row.scenarioId,
            count: row.count,
            failed: row.failed,
            avg: meanByScenario.get(row.scenarioId) ?? (scored?.scored ? scored.sum / scored.scored : null),
          }
        })
        .sort((a, b) => b.count - a.count)
    }
    const groups = new Map<string, { count: number; sum: number; scored: number; failed: number }>()
    for (const row of results) {
      if (row.agent_id !== agentId) continue
      const name = row.scenario?.name
      if (!name) continue
      const bucket = groups.get(name) ?? { count: 0, sum: 0, scored: 0, failed: 0 }
      bucket.count += 1
      if (row.status === 'failed') bucket.failed += 1
      const score = row.metric_scores?.[metricId]
      const value = typeof score?.value === 'number' ? score.value : Number(score?.value)
      if (!Number.isNaN(value) && score) {
        bucket.sum += value
        bucket.scored += 1
      }
      groups.set(name, bucket)
    }
    return Array.from(groups.entries())
      .map(([name, stats]) => ({
        name,
        scenarioId: results.find((r) => r.scenario?.name === name)?.scenario?.id,
        count: stats.count,
        failed: stats.failed,
        avg: stats.scored ? stats.sum / stats.scored : null,
      }))
      .sort((a, b) => b.count - a.count)
  }, [results, agentId, metricId, scenarioRows, agents, meanByScenario])

  if (!agentId) {
    return (
      <div className="space-y-4">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900">
          <ArrowLeft className="h-4 w-4" />
          Back to dashboard
        </button>
        <h2 className="text-lg font-semibold text-gray-900">Metric usage</h2>
        <p className="text-sm text-gray-500">{windowLabel} · click an agent to see metrics</p>
        <DrillChartPanel
          model={{
            headline: agents.reduce((sum, agent) => sum + agent.counts.total, 0).toLocaleString(),
            caption: 'Runs by agent',
            data: agents.map((agent) => ({ name: agent.agent_name, total: agent.counts.total })),
            series: [{ key: 'total', color: LAYER_LLM }],
            horizontal: true,
          }}
          onCategory={(name) => {
            const agent = agents.find((item) => item.agent_name === name)
            if (agent) onNavigate({ agentId: agent.agent_id })
          }}
        />
      </div>
    )
  }

  if (!metricId) {
    const list = scope === 'never' ? neverMetrics : metricsForAgent
    return (
      <div className="space-y-4">
        <button type="button" onClick={() => onNavigate({})} className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900">
          <ArrowLeft className="h-4 w-4" />
          Agents
        </button>
        <h2 className="text-lg font-semibold text-gray-900">{selectedAgent?.agent_name ?? 'Agent'}</h2>
        <div className="flex flex-wrap gap-1">
          {(['all', 'global', 'local', 'never'] as MetricScopeFilter[]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setScope(item)}
              className={`rounded-md border px-2.5 py-1 text-xs font-medium ${scope === item ? 'border-primary-200 bg-primary-50 text-primary-800' : 'border-gray-200 text-gray-600'}`}
            >
              {item === 'all' ? 'All' : item === 'global' ? 'Global' : item === 'local' ? 'Local' : 'Never used'}
            </button>
          ))}
        </div>
        {list.length > 0 ? (
          <DrillChartPanel
            model={{
              headline: list.length.toLocaleString(),
              caption: scope === 'never' ? 'Metrics never scored' : 'Scored runs by metric',
              data: list.map((metric) => ({
                name: metric.metric_name,
                count: metric.count === 0 ? 0 : metric.count,
              })),
              series: [{ key: 'count', color: LAYER_LLM }],
              horizontal: true,
            }}
            onCategory={(name) => {
              const metric = list.find((item) => item.metric_name === name)
              if (metric) onNavigate({ agentId, metricId: metric.metric_id })
            }}
          />
        ) : (
          <p className="rounded-xl border border-gray-200 bg-white px-4 py-6 text-sm text-gray-400">No metrics in this filter.</p>
        )}
      </div>
    )
  }

  const metric = metrics.find((item) => item.metric_id === metricId)
  const trend = scoreTrendForWindow(scoreDays, metricId ?? '', dateRange)

  if (!scenarioId) {
    return (
      <div className="space-y-4">
        <button type="button" onClick={() => onNavigate({ agentId })} className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900">
          <ArrowLeft className="h-4 w-4" />
          Metrics
        </button>
        <h2 className="text-lg font-semibold text-gray-900">{metric?.metric_name ?? 'Metric'}</h2>
        {trend.points.length > 0 ? (
          <DrillTrendChart points={trend.points} note={trend.note} />
        ) : (
          <p className="rounded-xl border border-gray-200 bg-white p-5 text-sm text-gray-400">No scored trend in this window.</p>
        )}
        {scenarios.length > 0 && (
          <>
            <DrillChartPanel
              model={{
                headline: formatChartNumber(metric?.mean),
                caption: 'Runs by scenario (bar length = run count)',
                data: scenarios.map((row) => ({ name: row.name, count: row.count })),
                series: [{ key: 'count', color: LAYER_LLM }],
                horizontal: true,
              }}
              onCategory={(name) => {
                const row = scenarios.find((item) => item.name === name)
                if (row) onNavigate({ agentId, metricId, scenarioId: row.scenarioId ?? row.name })
              }}
            />
            <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
              <h3 className="text-sm font-semibold text-gray-900">By scenario</h3>
              <ul className="mt-2 divide-y divide-gray-100">
                {scenarios.map((row) => (
                  <li key={row.name} className="flex items-center justify-between gap-3 py-2 text-sm text-gray-700">
                    <span className="truncate pr-3">{row.name}</span>
                    <span className="shrink-0 text-xs text-gray-500">
                      {row.count}
                      {row.avg != null ? ` · avg ${formatChartNumber(row.avg)}` : ''}
                      {` · ${row.count ? Math.round((row.failed / row.count) * 100) : 0}% fail`}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </div>
    )
  }

  const scenarioName = scenarios.find((row) => row.scenarioId === scenarioId)?.name ?? scenarioId
  return (
    <div className="space-y-4">
      <button
        type="button"
        onClick={() => onNavigate({ agentId, metricId })}
        className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900"
      >
        <ArrowLeft className="h-4 w-4" />
        {metric?.metric_name ?? 'Metric'}
      </button>
      <h2 className="text-lg font-semibold text-gray-900">{scenarioName}</h2>
      <PaginatedRunsTable
        base={runListBase}
        filterAgentId={agentId}
        filterScenarioId={scenarioId}
        metricId={metricId}
        onOpenResult={onOpenResult}
      />
    </div>
  )
}

export function TotalCallsDrill({
  agentRows,
  callDays,
  results: _results,
  runListBase,
  aggregateTotal,
  agentId,
  dateRange,
  allTime,
  onBack,
  onNavigate,
  onOpenResult,
}: {
  agentRows: Array<{ id: string; name: string; total: number }>
  callDays: Array<{ day: string; calls: number; sortKey?: string }>
  results: EvaluatorResultRow[]
  runListBase: RunListBase
  aggregateTotal: number
  agentId?: string
  dateRange: { start: string; end: string } | null
  allTime?: boolean
  onBack: () => void
  onNavigate: (agentId?: string) => void
  onOpenResult: (resultId: string) => void
}) {
  const windowLabel = formatDashboardWindowLabel(dateRange, allTime)
  const agent = agentRows.find((row) => row.id === agentId)
  const [dayKey, setDayKey] = useState<string | null>(null)
  const agentCallDays = callDays
  const dayListBase = dayKey ? toolsRunListBase(runListBase, dayKey) : runListBase

  if (!agentId) {
    return (
      <div className="space-y-4">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900">
          <ArrowLeft className="h-4 w-4" />
          Back to dashboard
        </button>
        <h2 className="text-lg font-semibold text-gray-900">Total calls · {aggregateTotal.toLocaleString()}</h2>
        <p className="text-sm text-gray-500">{windowLabel}</p>
        <DrillChartPanel
          model={{
            headline: aggregateTotal.toLocaleString(),
            caption: `Calls by agent · ${windowLabel}`,
            data: agentRows.map((row) => ({ name: row.name, total: row.total })),
            series: [{ key: 'total', color: LAYER_LLM }],
            horizontal: true,
          }}
          onCategory={(name) => {
            const row = agentRows.find((item) => item.name === name)
            if (row) onNavigate(row.id)
          }}
        />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <button type="button" onClick={() => onNavigate()} className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900">
        <ArrowLeft className="h-4 w-4" />
        By agent
      </button>
      <h2 className="text-lg font-semibold text-gray-900">{agent?.name ?? 'Agent'}</h2>
      <p className="text-sm text-gray-500">{agent?.total.toLocaleString() ?? '—'} calls · {windowLabel}</p>
      {agentCallDays.length > 0 && (
        <DrillChartPanel
          model={{
            headline: (agent?.total ?? agentCallDays.reduce((sum, day) => sum + day.calls, 0)).toLocaleString(),
            caption: 'Calls over time',
            data: agentCallDays.map((day) => ({
              day: day.day,
              sortKey: day.sortKey ?? String(day.day).slice(0, 10),
              calls: day.calls,
            })),
            series: [{ key: 'calls', color: LAYER_LLM }],
          }}
          display="area"
          onCategory={(label) => {
            const match = agentCallDays.find((day) => day.day === label)
            const next = match?.sortKey
            if (!next) return
            setDayKey((prev) => (prev === next ? null : next))
          }}
        />
      )}
      <PaginatedRunsTable
        base={dayListBase}
        filterAgentId={agentId}
        onOpenResult={onOpenResult}
        title={dayKey ? `Runs · ${formatChartDayLabel(dayKey, false)}` : 'Runs'}
      />
    </div>
  )
}