import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import { useState, useEffect } from 'react'
import { Profile as ProfileType, Invitation, UserUpdate, InvitationStatus } from '../../types/api'
import { User, Mail, Building2, CheckCircle, XCircle, KeyRound, AlertTriangle, ArrowRightLeft, Loader2 } from 'lucide-react'
import Button from '../../components/Button'
import { useAuthStore } from '../../store/authStore'

export default function Profile() {
  const queryClient = useQueryClient()
  const [isEditing, setIsEditing] = useState(false)
  const [name, setName] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')

  const { data: profile, isLoading: profileLoading } = useQuery<ProfileType>({
    queryKey: ['profile'],
    queryFn: () => apiClient.getProfile(),
  })

  // Separately call /auth/me to find out whether this user already has a
  // password set and whether their email is still the synthetic placeholder
  // we create for raw API-key users.
  const { data: authMe, refetch: refetchMe } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => apiClient.getMe(),
  })

  // --- Password / credential-linking form state ----------------------------
  // The form is collapsed by default; it only renders when the user clicks
  // "Set password" / "Change password". This keeps the profile page visually
  // quiet for users who aren't actively rotating their credentials.
  const [isEditingPassword, setIsEditingPassword] = useState(false)
  const [pwCurrent, setPwCurrent] = useState('')
  const [pwNew, setPwNew] = useState('')
  const [pwConfirm, setPwConfirm] = useState('')
  const [pwEmail, setPwEmail] = useState('')
  const [pwError, setPwError] = useState('')
  const [pwSuccess, setPwSuccess] = useState('')

  const resetPasswordForm = () => {
    setPwCurrent('')
    setPwNew('')
    setPwConfirm('')
    setPwEmail('')
    setPwError('')
  }

  const setPasswordMutation = useMutation({
    mutationFn: (data: { new_password: string; current_password?: string; email?: string }) =>
      apiClient.setPassword(data),
    onSuccess: (data) => {
      const hadPasswordBefore = !!authMe?.has_password
      setPwError('')
      setPwSuccess(
        hadPasswordBefore
          ? 'Password updated successfully.'
          : `Password set. You can now sign in with ${data.email} and your new password.`
      )
      resetPasswordForm()
      setIsEditingPassword(false)
      refetchMe()
      queryClient.invalidateQueries({ queryKey: ['profile'] })
    },
    onError: (err: any) => {
      setPwSuccess('')
      setPwError(err?.response?.data?.detail || 'Could not update password')
    },
  })

  const handlePasswordSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setPwError('')
    setPwSuccess('')
    if (pwNew.length < 8) {
      setPwError('Password must be at least 8 characters.')
      return
    }
    if (pwNew !== pwConfirm) {
      setPwError('Passwords do not match.')
      return
    }
    setPasswordMutation.mutate({
      new_password: pwNew,
      current_password: authMe?.has_password ? pwCurrent : undefined,
      email: authMe?.email_is_placeholder && pwEmail ? pwEmail : undefined,
    })
  }

  const openPasswordEditor = () => {
    resetPasswordForm()
    setPwSuccess('')
    setIsEditingPassword(true)
  }

  const closePasswordEditor = () => {
    resetPasswordForm()
    setIsEditingPassword(false)
  }

  // Update form fields when profile data loads
  useEffect(() => {
    if (profile) {
      setName(profile.name || '')
      setFirstName(profile.first_name || '')
      setLastName(profile.last_name || '')
      setEmail(profile.email)
    }
  }, [profile])

  const { data: invitations, isLoading: invitationsLoading } = useQuery({
    queryKey: ['profile', 'invitations'],
    queryFn: () => apiClient.getMyInvitations(),
  })

  const updateMutation = useMutation({
    mutationFn: (data: UserUpdate) => apiClient.updateProfile(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
      setIsEditing(false)
    },
  })

  // After a successful accept we remember what org the user just joined so
  // we can offer a one-click "Switch to <Org>" button. They can also reach
  // it later via the OrgSwitcher in the header - this is just the happy-path
  // shortcut right when they've joined.
  const { accessToken, switchOrg } = useAuthStore()
  const [justJoined, setJustJoined] = useState<
    | { organizationId: string; organizationName: string; role: string }
    | null
  >(null)
  const [isSwitchingToJoined, setIsSwitchingToJoined] = useState(false)
  const [switchError, setSwitchError] = useState('')

  const acceptInvitationMutation = useMutation({
    mutationFn: (invitation: Invitation) => apiClient.acceptInvitation(invitation.id),
    onSuccess: (_data, invitation) => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
      queryClient.invalidateQueries({ queryKey: ['iam'] })
      setJustJoined({
        organizationId: invitation.organization_id,
        organizationName: invitation.organization_name || 'the organization',
        role: invitation.role,
      })
    },
  })

  const handleJumpToJoinedOrg = async () => {
    if (!justJoined) return
    setSwitchError('')
    setIsSwitchingToJoined(true)
    try {
      await switchOrg(justJoined.organizationId)
      await queryClient.invalidateQueries()
      setJustJoined(null)
    } catch (err: any) {
      setSwitchError(err?.response?.data?.detail || 'Could not switch organization')
    } finally {
      setIsSwitchingToJoined(false)
    }
  }

  const declineInvitationMutation = useMutation({
    mutationFn: (invitationId: string) => apiClient.declineInvitation(invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile', 'invitations'] })
    },
  })

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    updateMutation.mutate({ 
      name: name || undefined, 
      first_name: firstName || undefined,
      last_name: lastName || undefined,
      email 
    })
  }

  const handleCancel = () => {
    setIsEditing(false)
    if (profile) {
      setName(profile.name || '')
      setFirstName(profile.first_name || '')
      setLastName(profile.last_name || '')
      setEmail(profile.email)
    }
  }

  const getRoleBadge = (role: string) => {
    const colors: Record<string, string> = {
      admin: 'bg-red-100 text-red-800',
      writer: 'bg-blue-100 text-blue-800',
      reader: 'bg-gray-100 text-gray-800',
    }
    return (
      <span className={`px-2 py-1 rounded-full text-xs font-medium ${colors[role.toLowerCase()] || 'bg-gray-100 text-gray-800'}`}>
        {role.charAt(0).toUpperCase() + role.slice(1)}
      </span>
    )
  }

  const getInvitationStatusBadge = (status: InvitationStatus) => {
    const colors: Record<string, string> = {
      pending: 'bg-yellow-100 text-yellow-800',
      accepted: 'bg-green-100 text-green-800',
      declined: 'bg-gray-100 text-gray-800',
      expired: 'bg-red-100 text-red-800',
    }
    return (
      <span className={`px-2 py-1 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
        {status.charAt(0).toUpperCase() + status.slice(1)}
      </span>
    )
  }

  if (profileLoading) {
    return <div className="text-center py-12 text-gray-500">Loading profile...</div>
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Profile</h1>
        <p className="mt-2 text-sm text-gray-600">Manage your personal information and invitations</p>
      </div>

      {/* Profile Information */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <User className="h-5 w-5" />
            Personal Information
          </h2>
          {!isEditing && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsEditing(true)}
            >
              Edit
            </Button>
          )}
        </div>
        <div className="p-6">
          {isEditing ? (
            <form onSubmit={handleSave} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label htmlFor="firstName" className="block text-sm font-medium text-gray-700 mb-1">
                    First Name
                  </label>
                  <input
                    id="firstName"
                    type="text"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="First name"
                  />
                </div>
                <div>
                  <label htmlFor="lastName" className="block text-sm font-medium text-gray-700 mb-1">
                    Last Name
                  </label>
                  <input
                    id="lastName"
                    type="text"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="Last name"
                  />
                </div>
              </div>
              <div>
                <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                  Full Name (Optional)
                </label>
                <input
                  id="name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="Your full name"
                />
              </div>
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="your@email.com"
                />
              </div>
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleCancel}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  isLoading={updateMutation.isPending}
                  className="flex-1"
                >
                  Save Changes
                </Button>
              </div>
            </form>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-500 mb-1">First Name</label>
                  <p className="text-gray-900">{profile?.first_name || 'Not set'}</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-500 mb-1">Last Name</label>
                  <p className="text-gray-900">{profile?.last_name || 'Not set'}</p>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-500 mb-1">Full Name</label>
                <p className="text-gray-900">{profile?.name || 'Not set'}</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-500 mb-1">Email</label>
                <p className="text-gray-900">{profile?.email}</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-500 mb-1">Member Since</label>
                <p className="text-gray-900">
                  {profile?.created_at ? new Date(profile.created_at).toLocaleDateString() : 'N/A'}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Security / Password linking */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <KeyRound className="h-5 w-5" />
              Sign-in Password
            </h2>
            <p className="mt-1 text-sm text-gray-600">
              {authMe?.has_password
                ? 'You can sign in with your email and password.'
                : 'No password set yet. Add one to sign in with email + password alongside your API key.'}
            </p>
          </div>
          {!isEditingPassword && (
            <Button
              variant="ghost"
              size="sm"
              onClick={openPasswordEditor}
              leftIcon={<KeyRound className="h-4 w-4" />}
            >
              {authMe?.has_password ? 'Change password' : 'Set password'}
            </Button>
          )}
        </div>

        <div className="p-6">
          {authMe?.email_is_placeholder && !authMe?.has_password && (
            <div className="mb-4 p-3 rounded-lg border border-amber-200 bg-amber-50 text-sm text-amber-900 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
              <div>
                Your account was created from an API key and uses a placeholder email
                (<code className="px-1 bg-amber-100 rounded">{authMe.email}</code>).
                Click <span className="font-medium">Set password</span> to replace it with a real email.
              </div>
            </div>
          )}

          {!isEditingPassword ? (
            <>
              {pwSuccess && (
                <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">
                  {pwSuccess}
                </div>
              )}
              {!authMe?.has_password && !authMe?.email_is_placeholder && !pwSuccess && (
                <p className="text-sm text-gray-500">
                  You currently sign in via API key or SSO only. Adding a password
                  is optional — it lets you also sign in via email + password on
                  the same account.
                </p>
              )}
            </>
          ) : (
            <form onSubmit={handlePasswordSubmit} className="space-y-4 max-w-lg">
              {authMe?.email_is_placeholder && !authMe?.has_password && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Real email</label>
                  <input
                    type="email"
                    value={pwEmail}
                    onChange={(e) => setPwEmail(e.target.value)}
                    required
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="you@example.com"
                  />
                </div>
              )}

              {authMe?.has_password && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Current password</label>
                  <input
                    type="password"
                    value={pwCurrent}
                    onChange={(e) => setPwCurrent(e.target.value)}
                    required
                    autoComplete="current-password"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  />
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">New password</label>
                <input
                  type="password"
                  value={pwNew}
                  onChange={(e) => setPwNew(e.target.value)}
                  required
                  minLength={8}
                  autoComplete="new-password"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Confirm new password</label>
                <input
                  type="password"
                  value={pwConfirm}
                  onChange={(e) => setPwConfirm(e.target.value)}
                  required
                  minLength={8}
                  autoComplete="new-password"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />
              </div>

              {pwError && (
                <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {pwError}
                </div>
              )}

              <div className="flex gap-3 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={closePasswordEditor}
                  disabled={setPasswordMutation.isPending}
                >
                  Cancel
                </Button>
                <Button type="submit" isLoading={setPasswordMutation.isPending}>
                  {authMe?.has_password ? 'Update password' : 'Set password'}
                </Button>
              </div>
            </form>
          )}
        </div>
      </div>

      {/* Organizations */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Building2 className="h-5 w-5" />
            Organizations
          </h2>
        </div>
        <div className="p-6">
          {profile?.organizations && profile.organizations.length > 0 ? (
            <div className="space-y-3">
              {profile.organizations.map((org) => (
                <div
                  key={org.id}
                  className="flex items-center justify-between p-4 border border-gray-200 rounded-lg"
                >
                  <div>
                    <div className="font-medium text-gray-900">{org.name}</div>
                    <div className="text-sm text-gray-500">
                      Joined {new Date(org.joined_at).toLocaleDateString()}
                    </div>
                  </div>
                  {getRoleBadge(org.role)}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">No organizations</div>
          )}
        </div>
      </div>

      {/* Post-accept switch prompt */}
      {justJoined && accessToken && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3">
          <CheckCircle className="h-5 w-5 text-green-600 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-green-900">
              You&apos;ve joined <span className="font-semibold">{justJoined.organizationName}</span>{' '}
              as {justJoined.role}.
            </div>
            <div className="text-xs text-green-800 mt-0.5">
              Your current session is still in your previous organization. Switch now to start working there.
            </div>
            {switchError && (
              <div className="text-xs text-red-700 mt-2">{switchError}</div>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <Button
              size="sm"
              onClick={handleJumpToJoinedOrg}
              disabled={isSwitchingToJoined}
              leftIcon={
                isSwitchingToJoined ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ArrowRightLeft className="h-4 w-4" />
                )
              }
            >
              {isSwitchingToJoined ? 'Switching…' : `Switch to ${justJoined.organizationName}`}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setJustJoined(null)
                setSwitchError('')
              }}
              disabled={isSwitchingToJoined}
            >
              Dismiss
            </Button>
          </div>
        </div>
      )}

      {/* Invitations */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Mail className="h-5 w-5" />
            My Invitations
          </h2>
        </div>
        <div className="p-6">
          {invitationsLoading ? (
            <div className="text-center py-8 text-gray-500">Loading invitations...</div>
          ) : invitations && invitations.length > 0 ? (
            <div className="space-y-4">
              {invitations.map((invitation: Invitation) => (
                <div
                  key={invitation.id}
                  className="flex items-center justify-between p-4 border border-gray-200 rounded-lg"
                >
                  <div className="flex-1">
                    <div className="font-medium text-gray-900">
                      {invitation.organization_name || 'Organization'}
                    </div>
                    <div className="text-sm text-gray-500">
                      Role: {invitation.role} • Invited {new Date(invitation.created_at).toLocaleDateString()}
                      {invitation.status === InvitationStatus.PENDING && (
                        <span className="ml-2">
                          • Expires {new Date(invitation.expires_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {getInvitationStatusBadge(invitation.status)}
                    {invitation.status === InvitationStatus.PENDING && (
                      <div className="flex gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => acceptInvitationMutation.mutate(invitation)}
                          isLoading={acceptInvitationMutation.isPending}
                          leftIcon={!acceptInvitationMutation.isPending ? <CheckCircle className="h-5 w-5" /> : undefined}
                          title="Accept invitation"
                          className="text-green-600 hover:bg-green-50 hover:text-green-700"
                        >
                          Accept
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => declineInvitationMutation.mutate(invitation.id)}
                          isLoading={declineInvitationMutation.isPending}
                          leftIcon={!declineInvitationMutation.isPending ? <XCircle className="h-5 w-5" /> : undefined}
                          title="Decline invitation"
                          className="text-red-600 hover:bg-red-50 hover:text-red-700"
                        >
                          Decline
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">No invitations</div>
          )}
        </div>
      </div>
    </div>
  )
}

