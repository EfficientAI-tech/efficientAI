import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, Building2, KeyRound, Loader2, LogOut, Users } from 'lucide-react'
import { Button, Chip, Switch } from '@heroui/react'
import Logo from '../../components/Logo'
import { apiClient, type PlatformOrganizationItem, type PlatformOrganizationStats } from '../../lib/api'
import { isPlatformAdminAuthenticated, usePlatformAdminStore } from '../../store/platformAdminStore'
import PlatformOrgMembersModal from './PlatformOrgMembersModal'
import PlatformSignupCodes from './PlatformSignupCodes'

type PlatformTab = 'organizations' | 'signup-codes'

const NAV_ITEMS: Array<{ key: PlatformTab; label: string; icon: typeof Building2 }> = [
  { key: 'organizations', label: 'Organizations', icon: Building2 },
  { key: 'signup-codes', label: 'Signup codes', icon: KeyRound },
]

export default function PlatformAdmin() {
  const navigate = useNavigate()
  const { admin, logout } = usePlatformAdminStore()
  const [activeTab, setActiveTab] = useState<PlatformTab>('organizations')
  const [stats, setStats] = useState<PlatformOrganizationStats | null>(null)
  const [organizations, setOrganizations] = useState<PlatformOrganizationItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [updatingOrgId, setUpdatingOrgId] = useState<string | null>(null)
  const [selectedOrg, setSelectedOrg] = useState<PlatformOrganizationItem | null>(null)

  const loadOrganizations = useCallback(async () => {
    setError('')
    setLoading(true)
    try {
      const [statsRes, orgsRes] = await Promise.all([
        apiClient.getPlatformOrganizationStats(),
        apiClient.listPlatformOrganizations({ limit: 200 }),
      ])
      setStats(statsRes)
      setOrganizations(orgsRes.items)
    } catch (err: any) {
      if (err?.response?.status === 401) {
        logout()
        navigate('/platform/login', { replace: true })
        return
      }
      setError(err?.response?.data?.detail || 'Failed to load organizations')
    } finally {
      setLoading(false)
    }
  }, [logout, navigate])

  useEffect(() => {
    if (!isPlatformAdminAuthenticated()) {
      navigate('/platform/login', { replace: true })
      return
    }
    if (activeTab === 'organizations') {
      loadOrganizations()
    }
  }, [activeTab, loadOrganizations, navigate])

  const handleToggleOrg = async (org: PlatformOrganizationItem, enabled: boolean) => {
    setUpdatingOrgId(org.id)
    setError('')
    try {
      const updated = await apiClient.updatePlatformOrganization(org.id, { is_active: enabled })
      setOrganizations((prev) => prev.map((item) => (item.id === org.id ? updated : item)))
      const statsRes = await apiClient.getPlatformOrganizationStats()
      setStats(statsRes)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to update organization')
    } finally {
      setUpdatingOrgId(null)
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/platform/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-gray-50 flex">
      <aside className="hidden md:flex md:w-64 md:flex-col bg-white border-r border-gray-200 flex-shrink-0">
        <div className="px-4 py-5 border-b border-gray-200">
          <Logo />
          <h1 className="mt-3 text-sm font-semibold text-gray-900">Platform Admin</h1>
          {admin && (
            <p className="mt-1 text-xs text-gray-500 truncate" title={admin.email}>
              {admin.email}
            </p>
          )}
        </div>

        <nav className="flex-1 px-2 py-4 space-y-1">
          {NAV_ITEMS.map(({ key, label, icon: Icon }) => {
            const isActive = activeTab === key
            return (
              <button
                key={key}
                type="button"
                onClick={() => setActiveTab(key)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-amber-50 text-amber-900 border border-amber-200'
                    : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900'
                }`}
              >
                <Icon className={`h-4 w-4 flex-shrink-0 ${isActive ? 'text-amber-700' : 'text-gray-400'}`} />
                {label}
              </button>
            )
          })}
        </nav>

        <div className="flex-shrink-0 border-t border-gray-200 p-4">
          <button
            type="button"
            onClick={handleLogout}
            className="w-full group flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900 transition-colors"
          >
            <LogOut className="h-5 w-5 text-gray-400 group-hover:text-gray-600 flex-shrink-0" />
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="md:hidden bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <Logo showText={false} />
            <p className="text-xs text-gray-500 truncate mt-1">{admin?.email}</p>
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 text-sm font-medium text-gray-700 hover:bg-gray-50 flex-shrink-0"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </header>

        <div className="md:hidden px-4 py-3 bg-white border-b border-gray-200 flex gap-2 overflow-x-auto">
          {NAV_ITEMS.map(({ key, label, icon: Icon }) => {
            const isActive = activeTab === key
            return (
              <button
                key={key}
                type="button"
                onClick={() => setActiveTab(key)}
                className={`flex items-center gap-2 px-3 py-2 rounded-full text-sm font-medium whitespace-nowrap flex-shrink-0 ${
                  isActive
                    ? 'bg-amber-100 text-amber-900 border border-amber-200'
                    : 'bg-gray-100 text-gray-600'
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </button>
            )
          })}
        </div>

        <main className="flex-1 max-w-6xl w-full mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6">
          <div className="hidden md:block">
            <h2 className="text-xl font-semibold text-gray-900">
              {NAV_ITEMS.find((item) => item.key === activeTab)?.label}
            </h2>
            {admin && <p className="text-sm text-gray-500 mt-1">Signed in as {admin.email}</p>}
          </div>

          {error && activeTab === 'organizations' && (
            <Chip color="danger" variant="flat" startContent={<AlertCircle className="w-4 h-4" />} className="w-full max-w-full h-auto py-2">
              {error}
            </Chip>
          )}

          {activeTab === 'organizations' && (
            <>
              {stats && (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <StatCard label="Total organizations" value={stats.total} />
                  <StatCard label="Active" value={stats.active} />
                  <StatCard label="Disabled" value={stats.disabled} />
                </div>
              )}

              <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
                  <h2 className="font-medium text-gray-900">Organizations</h2>
                  {loading && <Loader2 className="h-4 w-4 animate-spin text-gray-400" />}
                </div>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="bg-gray-50 text-left text-gray-500">
                      <tr>
                        <th className="px-4 py-3 font-medium">Name</th>
                        <th className="px-4 py-3 font-medium">Organization ID</th>
                        <th className="px-4 py-3 font-medium">Members</th>
                        <th className="px-4 py-3 font-medium">Status</th>
                        <th className="px-4 py-3 font-medium">Enabled</th>
                        <th className="px-4 py-3 font-medium">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {organizations.map((org) => (
                        <tr key={org.id} className="border-t border-gray-100">
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <Building2 className="h-4 w-4 text-gray-400" />
                              <span className="font-medium text-gray-900">{org.name}</span>
                            </div>
                          </td>
                          <td className="px-4 py-3 font-mono text-xs text-gray-600">{org.id}</td>
                          <td className="px-4 py-3 text-gray-700">{org.member_count}</td>
                          <td className="px-4 py-3">
                            <Chip size="sm" color={org.is_active ? 'success' : 'danger'} variant="flat">
                              {org.is_active ? 'Active' : 'Disabled'}
                            </Chip>
                          </td>
                          <td className="px-4 py-3">
                            <Switch
                              isSelected={org.is_active}
                              isDisabled={updatingOrgId === org.id}
                              onValueChange={(enabled) => handleToggleOrg(org, enabled)}
                              aria-label={`Toggle ${org.name}`}
                            />
                          </td>
                          <td className="px-4 py-3">
                            <Button
                              size="sm"
                              variant="flat"
                              startContent={<Users className="h-4 w-4" />}
                              onPress={() => setSelectedOrg(org)}
                            >
                              Members
                            </Button>
                          </td>
                        </tr>
                      ))}
                      {!loading && organizations.length === 0 && (
                        <tr>
                          <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                            No organizations found.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}

          {activeTab === 'signup-codes' && <PlatformSignupCodes />}
        </main>
      </div>

      {selectedOrg && (
        <PlatformOrgMembersModal org={selectedOrg} onClose={() => setSelectedOrg(null)} />
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl px-4 py-5">
      <div className="text-sm text-gray-500">{label}</div>
      <div className="text-2xl font-semibold text-gray-900 mt-1">{value}</div>
    </div>
  )
}
