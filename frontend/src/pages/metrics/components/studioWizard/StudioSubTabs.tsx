import { useSearchParams } from 'react-router-dom'

export type StudioPageTab = 'setup' | 'results'

export function studioTabFromSearch(value: string | null): StudioPageTab {
  return value === 'results' ? 'results' : 'setup'
}

export default function StudioSubTabs() {
  const [searchParams, setSearchParams] = useSearchParams()
  const active = studioTabFromSearch(searchParams.get('tab'))

  const selectTab = (tab: StudioPageTab) => {
    const next = new URLSearchParams(searchParams)
    if (tab === 'setup') {
      next.delete('tab')
    } else {
      next.set('tab', 'results')
    }
    setSearchParams(next, { replace: true })
  }

  return (
    <div className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5 text-sm font-medium">
      {(
        [
          { id: 'setup' as const, label: 'Setup' },
          { id: 'results' as const, label: 'Results' },
        ] as const
      ).map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => selectTab(tab.id)}
          className={`px-4 py-2 rounded-md transition-colors ${
            active === tab.id
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-600 hover:text-gray-900'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
