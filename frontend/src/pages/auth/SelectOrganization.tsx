import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Building2, Loader2 } from 'lucide-react'
import Logo from '../../components/Logo'
import { Card, CardBody } from '@heroui/react'
import { apiClient } from '../../lib/api'
import { useAuthStore } from '../../store/authStore'
import { useOrgSwitch } from '../../hooks/useOrgSwitch'
import OrgReauthModal from '../../components/OrgReauthModal'

export default function SelectOrganization() {
  const navigate = useNavigate()
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

  const { data: profile, isLoading } = useQuery({
    queryKey: ['profile'],
    queryFn: () => apiClient.getProfile(),
    enabled: !!user && !apiKey,
  })

  if (!user || apiKey) {
    navigate('/login', { replace: true })
    return null
  }

  const orgs = profile?.organizations ?? []

  const handleSelect = async (orgId: string, orgName: string) => {
    const switched = await switchToOrg(orgId, orgName)
    if (switched) {
      navigate('/', { replace: true })
    }
  }

  const handleReauthSuccess = async (password: string) => {
    const ok = await submitReauth(password)
    if (ok) {
      navigate('/', { replace: true })
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-amber-50 via-yellow-50 to-orange-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8 relative z-10">
        <div className="text-center">
          <div className="flex justify-center mb-4">
            <Logo textSize="xl" />
          </div>
          <p className="mt-2 text-sm text-gray-600">Choose an organization to continue</p>
        </div>

        <Card className="shadow-xl">
          <CardBody className="p-6">
            {isLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-gray-500" />
              </div>
            ) : orgs.length === 0 ? (
              <p className="text-sm text-gray-600 text-center">
                No organizations found for your account.
              </p>
            ) : (
              <div className="space-y-2">
                {orgs.map((org) => {
                  const isSwitching = switchingTo === org.id
                  return (
                    <button
                      key={org.id}
                      type="button"
                      disabled={!!switchingTo}
                      onClick={() => handleSelect(org.id, org.name)}
                      className="w-full px-4 py-3 text-left border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors flex items-center gap-3 disabled:opacity-60"
                    >
                      <Building2 className="h-5 w-5 text-gray-500 flex-shrink-0" />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-gray-900 truncate">{org.name}</div>
                        <div className="text-xs text-gray-500 capitalize">{org.role}</div>
                      </div>
                      {isSwitching && (
                        <Loader2 className="h-4 w-4 text-gray-400 animate-spin flex-shrink-0" />
                      )}
                    </button>
                  )
                })}
              </div>
            )}
            {error && (
              <p className="mt-4 text-sm text-red-700 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                {error}
              </p>
            )}
          </CardBody>
        </Card>
      </div>

      <OrgReauthModal
        open={!!reauthTarget}
        organizationName={reauthTarget?.name ?? ''}
        email={authUser?.email}
        isLoading={reauthLoading}
        error={reauthError}
        onClose={closeReauth}
        onSubmit={handleReauthSuccess}
      />
    </div>
  )
}
