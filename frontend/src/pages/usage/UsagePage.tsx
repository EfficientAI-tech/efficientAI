import { useEffect } from 'react'
import { Activity, DollarSign } from 'lucide-react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { useIsAdmin } from '../../hooks/useRole'
import { useLicenseStore } from '../../store/licenseStore'
import Usage from './Usage'
import UsagePricing from './UsagePricing'

type UsageTab = 'overview' | 'pricing'

export default function UsagePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const isAdmin = useIsAdmin()
  const licenseLoaded = useLicenseStore((s) => s.isLoaded)
  const hasExtendedHistory = useLicenseStore((s) => s.hasExtendedUsageHistory())
  const canManagePricing = isAdmin && licenseLoaded && hasExtendedHistory

  const tabParam = searchParams.get('tab')
  const activeTab: UsageTab =
    tabParam === 'pricing' && canManagePricing ? 'pricing' : 'overview'

  useEffect(() => {
    if (tabParam === 'pricing' && !canManagePricing) {
      setSearchParams({}, { replace: true })
    }
  }, [tabParam, canManagePricing, setSearchParams])

  const setActiveTab = (tab: UsageTab) => {
    setSearchParams(tab === 'pricing' ? { tab: 'pricing' } : {}, { replace: true })
  }

  const tabs: Array<{ id: UsageTab; label: string; icon: typeof Activity; hidden?: boolean }> = [
    { id: 'overview', label: 'Overview', icon: Activity },
    { id: 'pricing', label: 'Pricing overrides', icon: DollarSign, hidden: !canManagePricing },
  ]

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-gray-900">Usage</h1>

      {canManagePricing ? (
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex gap-6" aria-label="Usage sections">
            {tabs
              .filter((tab) => !tab.hidden)
              .map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setActiveTab(id)}
                  className={`flex items-center gap-2 whitespace-nowrap border-b-2 px-1 py-2.5 text-sm font-medium transition-colors ${
                    activeTab === id
                      ? 'border-primary-600 text-primary-600'
                      : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </button>
              ))}
          </nav>
        </div>
      ) : null}

      {activeTab === 'overview' ? <Usage /> : <UsagePricing />}
    </div>
  )
}

export function UsagePricingRedirect() {
  return <Navigate to="/usage?tab=pricing" replace />
}
