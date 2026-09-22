import { Link, useLocation } from 'react-router-dom'
import { BarChart3, Lock, Sparkles, type LucideIcon } from 'lucide-react'
import { useLicenseStore } from '../../../store/licenseStore'

type MetricsTab = {
  id: string
  label: string
  href: string
  icon: LucideIcon
  enterpriseFeature?: string
}

const TABS: MetricsTab[] = [
  { id: 'metrics', label: 'Metrics', href: '/metrics-management', icon: BarChart3 },
  { id: 'studio', label: 'Studio', href: '/metrics-management/studio', icon: Sparkles, enterpriseFeature: 'metric_studio' },
]

export default function MetricsTabBar() {
  const location = useLocation()
  const isFeatureEnabled = useLicenseStore((s) => s.isFeatureEnabled)

  const isStudio = location.pathname.startsWith('/metrics-management/studio')

  return (
    <div className="border-b border-gray-200">
      <nav className="-mb-px flex gap-6 overflow-x-auto" aria-label="Metrics sections">
        {TABS.map((tab) => {
          const active = tab.id === 'studio' ? isStudio : !isStudio
          const Icon = tab.icon
          const isGated = tab.enterpriseFeature && !isFeatureEnabled(tab.enterpriseFeature)
          return (
            <Link
              key={tab.id}
              to={tab.href}
              className={`flex items-center gap-2 px-1 py-3 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
                active
                  ? 'border-primary-600 text-primary-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              } ${isGated ? 'opacity-80' : ''}`}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
              {isGated && <Lock className="h-3 w-3 text-amber-600" aria-label="Enterprise feature" />}
            </Link>
          )
        })}
      </nav>
    </div>
  )
}
