import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Check, ChevronDown, Loader2 } from 'lucide-react'
import { apiClient } from '../lib/api'
import { useAuthStore } from '../store/authStore'
import type { Profile } from '../types/api'

/**
 * Organization switcher dropdown.
 *
 * Shown only when:
 *   - The user has a Bearer session (API keys are per-tenant by design and
 *     can't switch orgs).
 *   - The user is a member of more than one organization.
 *
 * On selection, calls POST /auth/switch-org which returns a new Bearer token
 * pinned to the target org. We swap it into the auth store and invalidate
 * all react-query caches so every view refetches against the new tenant.
 */
export default function OrgSwitcher() {
  const { accessToken, user, switchOrg } = useAuthStore()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [switchingTo, setSwitchingTo] = useState<string | null>(null)
  const [error, setError] = useState<string>('')

  const { data: profile } = useQuery<Profile>({
    queryKey: ['profile'],
    queryFn: () => apiClient.getProfile(),
    enabled: !!accessToken,
  })

  // Hide entirely for API-key sessions or single-org users - no switching
  // makes sense there, and the clutter isn't worth it.
  if (!accessToken) return null
  const orgs = profile?.organizations ?? []
  if (orgs.length <= 1) return null

  const currentOrgId = user?.organization_id
  const currentOrg = orgs.find((o) => o.id === currentOrgId) ?? orgs[0]

  const handleSwitch = async (orgId: string) => {
    if (orgId === currentOrgId) {
      setOpen(false)
      return
    }
    setError('')
    setSwitchingTo(orgId)
    try {
      await switchOrg(orgId)
      // Blow away every cached query so the UI refetches against the new
      // tenant. Individual pages read org-scoped data and we don't want
      // any stale rows from the old org leaking through.
      await queryClient.invalidateQueries()
      setOpen(false)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not switch organization')
    } finally {
      setSwitchingTo(null)
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 hover:border-gray-300 transition-all shadow-sm max-w-[220px]"
        title="Switch organization"
      >
        <Building2 className="h-4 w-4 text-gray-500 flex-shrink-0" />
        <span className="truncate">{currentOrg?.name ?? 'Organization'}</span>
        <ChevronDown className="h-4 w-4 text-gray-500 flex-shrink-0" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 mt-2 w-72 bg-white rounded-lg shadow-lg border border-gray-200 z-20">
            <div className="px-4 py-2 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Your organizations
            </div>
            <div className="max-h-80 overflow-y-auto py-1">
              {orgs.map((org) => {
                const isCurrent = org.id === currentOrgId
                const isSwitching = switchingTo === org.id
                return (
                  <button
                    key={org.id}
                    type="button"
                    disabled={isSwitching}
                    onClick={() => handleSwitch(org.id)}
                    className={`w-full px-4 py-2.5 text-left hover:bg-gray-50 transition-colors flex items-center justify-between gap-2 ${
                      isCurrent ? 'bg-primary-50' : ''
                    } disabled:opacity-60`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-gray-900 truncate">
                        {org.name}
                      </div>
                      <div className="text-xs text-gray-500 capitalize">
                        {org.role}
                      </div>
                    </div>
                    {isSwitching ? (
                      <Loader2 className="h-4 w-4 text-gray-400 animate-spin flex-shrink-0" />
                    ) : isCurrent ? (
                      <Check className="h-4 w-4 text-primary-600 flex-shrink-0" />
                    ) : null}
                  </button>
                )
              })}
            </div>
            {error && (
              <div className="px-4 py-2 border-t border-gray-100 text-xs text-red-700 bg-red-50">
                {error}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
