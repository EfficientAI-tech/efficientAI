import { Edit, FileText, Plus, Trash2 } from 'lucide-react'
import Button from '../../components/Button'
import { markdownPreview } from './scenarioMarkdown'
import type { Scenario } from './scenarioTypes'

interface ScenariosListPanelProps {
  agentLabel: string
  scenarios: Scenario[]
  onCreateScenario: () => void
  onEditScenario: (scenario: Scenario) => void
  onDeleteScenario: (scenario: Scenario) => void
  onViewScenario?: (scenario: Scenario) => void
}

export default function ScenariosListPanel({
  agentLabel,
  scenarios,
  onCreateScenario,
  onEditScenario,
  onDeleteScenario,
  onViewScenario,
}: ScenariosListPanelProps) {
  return (
    <section className="flex-1 min-w-0 rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden flex flex-col max-h-[70vh] lg:max-h-[calc(100vh-11rem)]">
      <div className="px-5 py-4 border-b border-gray-100 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-gray-900 truncate">{agentLabel}</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            {scenarios.length === 0
              ? 'No scenarios for this agent yet'
              : `${scenarios.length} scenario${scenarios.length !== 1 ? 's' : ''}`}
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={onCreateScenario} leftIcon={<Plus className="h-4 w-4" />}>
          Create Scenario
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {scenarios.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full min-h-[240px] text-center px-4">
            <FileText className="h-10 w-10 text-gray-300 mb-3" />
            <h3 className="text-sm font-medium text-gray-900 mb-1">No scenarios yet</h3>
            <p className="text-sm text-gray-500 mb-4 max-w-sm">
              Create a scenario for {agentLabel} or generate one from the agent prompt.
            </p>
            <Button variant="outline" size="sm" onClick={onCreateScenario} leftIcon={<Plus className="h-4 w-4" />}>
              Create Scenario
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            {scenarios.map((scenario) => (
              <article
                key={scenario.id}
                className="group rounded-lg border border-gray-200 bg-white hover:border-primary-200 hover:shadow-sm transition-all"
              >
                <div className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <button
                      type="button"
                      onClick={() => onViewScenario?.(scenario)}
                      className="min-w-0 flex-1 text-left"
                    >
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4 text-gray-400 shrink-0" />
                        <h3 className="text-sm font-semibold text-gray-900 group-hover:text-primary-700 truncate">
                          {scenario.name}
                        </h3>
                      </div>
                      <p className="text-sm text-gray-600 mt-2 line-clamp-3 leading-relaxed">
                        {scenario.description
                          ? markdownPreview(scenario.description, 220)
                          : 'No description'}
                      </p>
                      {Object.keys(scenario.required_info).length > 0 ? (
                        <p className="text-xs text-gray-400 mt-2">
                          {Object.keys(scenario.required_info).length} required info field
                          {Object.keys(scenario.required_info).length !== 1 ? 's' : ''}
                        </p>
                      ) : null}
                    </button>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        type="button"
                        onClick={() => onEditScenario(scenario)}
                        className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                        title="Edit scenario"
                      >
                        <Edit className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => onDeleteScenario(scenario)}
                        className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                        title="Delete scenario"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
