export type ProductionAgentSubTab = 'prompt' | 'knowledge_bases' | 'tools'

const SUB_TABS: { id: ProductionAgentSubTab; label: string }[] = [
  { id: 'prompt', label: 'Prompt' },
  { id: 'knowledge_bases', label: 'Knowledge Bases' },
  { id: 'tools', label: 'Tools' },
]

export default function ProductionAgentSubTabNav({
  value,
  onChange,
}: {
  value: ProductionAgentSubTab
  onChange: (tab: ProductionAgentSubTab) => void
}) {
  return (
    <div
      className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5"
      role="tablist"
      aria-label="Production agent sections"
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
