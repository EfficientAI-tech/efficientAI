export type TestAgentSubTab = 'configuration' | 'prompt'

const SUB_TABS: { id: TestAgentSubTab; label: string }[] = [
  { id: 'prompt', label: 'Prompt' },
  { id: 'configuration', label: 'Configuration' },
]

export default function TestAgentSubTabNav({
  value,
  onChange,
}: {
  value: TestAgentSubTab
  onChange: (tab: TestAgentSubTab) => void
}) {
  return (
    <div
      className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5"
      role="tablist"
      aria-label="Test agent sections"
    >
      {SUB_TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={value === tab.id}
          onClick={() => onChange(tab.id)}
          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
            value === tab.id
              ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200'
              : 'text-gray-600 hover:text-gray-900'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
