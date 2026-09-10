import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Building2, Check, ChevronDown, Loader2 } from 'lucide-react'
import { apiClient } from '../lib/api'
import { useAuthStore } from '../store/authStore'
import { useOrgSwitch } from '../hooks/useOrgSwitch'
import OrgReauthModal from './OrgReauthModal'
import type { Profile } from '../types/api'

export default function OrgSwitcher() {
  const { apiKey, user } = useAuthStore()
  const {
    switchingTo,
    error,
    reauthTarget,
    reauthError,
    reauthLoading,
    switchToOrg,
    closeReauth,
    submitReauth,
    user: authUser,
  } = useOrgSwitch()
  const [open, setOpen] = useState(false)

  const { data: profile } = useQuery<Profile>({
    queryKey: ['profile'],
    queryFn: () => apiClient.getProfile(),
    enabled: !!user && !apiKey,
  })

  if (!user || apiKey) return null
  const orgs = profile?.organizations ?? []
  if (orgs.length <= 1) return null

  const currentOrgId = user?.organization_id
  const currentOrg = orgs.find((o) => o.id === currentOrgId) ?? orgs[0]

  const handleSwitch = async (orgId: string, orgName: string) => {
    if (orgId === currentOrgId) {
      setOpen(false)
      return
    }
    const switched = await switchToOrg(orgId, orgName)
    if (switched) {
      setOpen(false)
    }
  }

  return (
    <>
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
                      disabled={!!switchingTo}
                      onClick={() => handleSwitch(org.id, org.name)}
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

      <OrgReauthModal
        open={!!reauthTarget}
        organizationName={reauthTarget?.name ?? ''}
        email={authUser?.email}
        isLoading={reauthLoading}
        error={reauthError}
        onClose={closeReauth}
        onSubmit={async (password) => {
          await submitReauth(password)
        }}
      />
    </>
  )
}
