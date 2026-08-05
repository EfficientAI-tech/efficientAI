import { Link, useLocation } from 'react-router-dom'

const TABS = [
  { id: 'manage', label: 'Manage', href: '/metrics-management' },
  { id: 'studio', label: 'Studio', href: '/metrics-management/studio' },
] as const

export default function MetricsTabBar() {
  const location = useLocation()

  const isStudio =
    location.pathname.startsWith('/metrics-management/studio')

  return (
    <div className="inline-flex rounded-md border border-gray-200 bg-gray-50 p-1 text-sm font-medium">
      {TABS.map((tab) => {
        const active =
          tab.id === 'studio' ? isStudio : !isStudio
        return (
          <Link
            key={tab.id}
            to={tab.href}
            className={`px-4 py-2 rounded transition-colors ${
              active
                ? 'bg-white text-gray-900 shadow-sm border border-gray-200'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            {tab.label}
          </Link>
        )
      })}
    </div>
  )
}
