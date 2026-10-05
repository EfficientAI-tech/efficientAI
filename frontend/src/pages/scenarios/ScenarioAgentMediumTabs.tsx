import { agentMediumFilterLabel, type AgentMediumFilter } from '../../lib/agentMedium'

interface ScenarioAgentMediumTabsProps {
  value: AgentMediumFilter
  onChange: (value: AgentMediumFilter) => void
  className?: string
}

export default function ScenarioAgentMediumTabs({
  value,
  onChange,
  className = '',
}: ScenarioAgentMediumTabsProps) {
  return (
    <div className={`flex gap-1 ${className}`} role="tablist" aria-label="Agent medium">
      {(['voice', 'chat'] as const).map((key) => (
        <button
          key={key}
          type="button"
          role="tab"
          aria-selected={value === key}
          onClick={() => onChange(key)}
          className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium border transition-colors ${
            value === key
              ? 'border-primary-300 bg-primary-50 text-primary-800'
              : 'border-gray-200 text-gray-600 hover:bg-gray-100'
          }`}
        >
          {agentMediumFilterLabel(key)}
        </button>
      ))}
    </div>
  )
}
