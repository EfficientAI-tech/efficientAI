import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useState, useEffect } from 'react'
import { Profile as ProfileType, Invitation, UserUpdate, InvitationStatus } from '../types/api'
import { User, Mail, Building2, CheckCircle, XCircle } from 'lucide-react'
import Button from '../components/Button'

export default function Profile() {
  const queryClient = useQueryClient()
  const [isEditing, setIsEditing] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')

  const { data: profile, isLoading: profileLoading } = useQuery<ProfileType>({
    queryKey: ['profile'],
    queryFn: () => apiClient.getProfile(),
  })

  // Update form fields when profile data loads
  useEffect(() => {
    if (profile) {
      setName(profile.name || '')
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

  const acceptInvitationMutation = useMutation({
    mutationFn: (invitationId: string) => apiClient.acceptInvitation(invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
      queryClient.invalidateQueries({ queryKey: ['iam'] })
    },
  })

  const declineInvitationMutation = useMutation({
    mutationFn: (invitationId: string) => apiClient.declineInvitation(invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile', 'invitations'] })
    },
  })

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    updateMutation.mutate({ name: name || undefined, email })
  }

  const handleCancel = () => {
    setIsEditing(false)
    if (profile) {
      setName(profile.name || '')
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
              <div>
                <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                  Name
                </label>
                <input
                  id="name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="Your name"
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
              <div>
                <label className="block text-sm font-medium text-gray-500 mb-1">Name</label>
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
                          onClick={() => acceptInvitationMutation.mutate(invitation.id)}
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

