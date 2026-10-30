import CallHits from './CallHits'
import { outcomeNotAchieved } from './dashboardSelectors'
import { useDashboardNav } from './dashboardNav'
import { useDashboardFilters } from './useDashboardFilters'
import SectionShell from './SectionShell'

export default function FailuresSection() {
  const nav = useDashboardNav()
  const filters = useDashboardFilters()
  const toolFails = nav.calls.filter((call) => call.computed.toolCallFailures > 0)
  const outcomeFails = nav.calls.filter(outcomeNotAchieved)
  const kind = filters.failKind
  const shown = kind === 'outcome' ? outcomeFails : kind === 'tool' ? toolFails : [...toolFails, ...outcomeFails.filter((call) => !toolFails.includes(call))]

  return (
    <SectionShell section="failures" current="Failures" onBack={nav.openOverview}>
      <h1 className="text-2xl font-semibold text-gray-900">Failures</h1>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => nav.openFailures('tool')}
          className={`rounded-lg border px-3 py-2 text-sm ${kind === 'tool' ? 'border-gray-900 bg-gray-900 text-white' : 'border-gray-200 bg-white'}`}
        >
          Tool calls failed · {toolFails.length}
        </button>
        <button
          type="button"
          onClick={() => nav.openFailures('outcome')}
          className={`rounded-lg border px-3 py-2 text-sm ${kind === 'outcome' ? 'border-gray-900 bg-gray-900 text-white' : 'border-gray-200 bg-white'}`}
        >
          Outcomes not achieved · {outcomeFails.length}
        </button>
      </div>
      <CallHits
        calls={shown}
        currency={nav.currency}
        onOpenCall={nav.openCall}
        extra={(call) =>
          kind === 'outcome' || outcomeNotAchieved(call)
            ? String(call.metric_scores['mock-metric-outcome']?.value ?? 'unresolved')
            : `${call.computed.toolCallFailures} tool fail`
        }
      />
    </SectionShell>
  )
}
