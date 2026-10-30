import CallHits from './CallHits'
import InsightTrendChart from './charts/InsightTrendChart'
import {
  callsForIntegration,
  callsForTool,
  integrationUsageOverTime,
  toolUsageOverTime,
  toolsOnCall,
} from './dashboardSelectors'
import { useDashboardNav } from './dashboardNav'
import { useDashboardFilters } from './useDashboardFilters'
import { MOCK_TOOLS, USE_CASE_INTEGRATION, integrationByNameOrId } from './mockCatalog'
import SectionShell from './SectionShell'

export default function ToolDetailSection() {
  const nav = useDashboardNav()
  const filters = useDashboardFilters()
  const key = filters.toolName ?? 'Tool'
  const integration = integrationByNameOrId(key)
  const isUseCase = MOCK_TOOLS.includes(key as (typeof MOCK_TOOLS)[number])
  const name = integration?.name ?? key
  const series = (integration ? integrationUsageOverTime(nav.calls, integration.id) : toolUsageOverTime(nav.calls, key)).map(
    (row) => ({ label: row.day.slice(5), value: row.value }),
  )
  const hits = integration ? callsForIntegration(nav.calls, integration.id) : callsForTool(nav.calls, key)
  const color = integration?.color ?? '#7c3aed'
  const linked = isUseCase ? integrationByNameOrId(USE_CASE_INTEGRATION[key as keyof typeof USE_CASE_INTEGRATION] ?? '') : null

  return (
    <SectionShell section="tool" current={name} onBack={integration ? nav.openTools : nav.openToolCalls}>
      <div>
        <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-gray-400">
          {integration ? 'Tool' : 'Use case'}
        </p>
        <h1 className="text-2xl font-semibold text-gray-900">{name}</h1>
        {linked && (
          <button type="button" className="mt-1 text-sm hover:underline" style={{ color: linked.color }} onClick={() => nav.openTool(linked.id)}>
            Runs on {linked.name}
          </button>
        )}
      </div>
      <section className="rounded-xl border border-gray-200 bg-white p-4">
        <p className="mb-2 text-sm font-medium text-gray-900">Usage over time</p>
        <InsightTrendChart points={series} kind="area" color={color} height={220} />
      </section>
      <div>
        <p className="mb-2 text-sm font-medium text-gray-900">
          {integration ? 'Calls using this tool' : 'Calls using this use case'}
        </p>
        <CallHits
          calls={hits}
          currency={nav.currency}
          onOpenCall={nav.openCall}
          extra={(call) => {
            const tools = toolsOnCall(call).filter((tool) =>
              integration
                ? tool.integration === integration.id || tool.integration === integration.name
                : tool.name === key,
            )
            const failed = tools.filter((tool) => tool.failed).length
            const useCases = integration ? [...new Set(tools.map((tool) => tool.name))].join(', ') : null
            const suffix = failed ? `${tools.length} uses · ${failed} failed` : `${tools.length} uses`
            return useCases ? `${suffix} · ${useCases}` : suffix
          }}
        />
      </div>
    </SectionShell>
  )
}
