import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useState } from 'react'
import { Role, Invitation, OrganizationMember, InvitationCreate } from '../types/api'
import { Users, Mail, UserPlus, Shield, ShieldCheck, ShieldAlert, X, Trash2 } from 'lucide-react'

export default function IAM() {
  const queryClient = useQueryClient()
  const [showInviteModal, setShowInviteModal] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<Role>(Role.READER)

  const { data: users, isLoading: usersLoading } = useQuery({
    queryKey: ['iam', 'users'],
    queryFn: () => apiClient.listOrganizationUsers(),
  })

  const { data: invitations, isLoading: invitationsLoading } = useQuery({
    queryKey: ['iam', 'invitations'],
    queryFn: () => apiClient.listInvitations(),
  })

  const inviteMutation = useMutation({
    mutationFn: (data: InvitationCreate) => apiClient.inviteUser(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['iam'] })
      setShowInviteModal(false)
      setInviteEmail('')
      setInviteRole(Role.READER)
    },
  })

  const updateRoleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) =>
      apiClient.updateUserRole(userId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['iam', 'users'] })
    },
  })

  const removeUserMutation = useMutation({
    mutationFn: (userId: string) => apiClient.removeUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['iam', 'users'] })
    },
  })

  const cancelInvitationMutation = useMutation({
    mutationFn: (invitationId: string) => apiClient.cancelInvitation(invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['iam', 'invitations'] })
    },
  })

  const handleInvite = (e: React.FormEvent) => {
    e.preventDefault()
    inviteMutation.mutate({ email: inviteEmail, role: inviteRole })
  }

  const getRoleIcon = (role: Role) => {
    switch (role) {
      case Role.ADMIN:
        return <ShieldAlert className="h-5 w-5 text-red-500" />
      case Role.WRITER:
        return <ShieldCheck className="h-5 w-5 text-blue-500" />
      case Role.READER:
        return <Shield className="h-5 w-5 text-gray-500" />
    }
  }

  const getRoleBadge = (role: Role) => {
    const colors = {
      [Role.ADMIN]: 'bg-red-100 text-red-800',
      [Role.WRITER]: 'bg-blue-100 text-blue-800',
      [Role.READER]: 'bg-gray-100 text-gray-800',
    }
    return (
      <span className={`px-2 py-1 rounded-full text-xs font-medium ${colors[role]}`}>
        {role.charAt(0).toUpperCase() + role.slice(1)}
      </span>
    )
  }

  const getInvitationStatusBadge = (status: string) => {
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

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Identity & Access Management</h1>
          <p className="mt-2 text-sm text-gray-600">
            Manage users and their permissions in your organization
          </p>
        </div>
        <button
          onClick={() => setShowInviteModal(true)}
          className="flex items-center gap-2 bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700 transition-colors"
        >
          <UserPlus className="h-5 w-5" />
          Invite User
        </button>
      </div>

      {/* Users Section */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Users className="h-5 w-5" />
            Organization Members
          </h2>
        </div>
        <div className="p-6">
          {usersLoading ? (
            <div className="text-center py-8 text-gray-500">Loading users...</div>
          ) : users && users.length > 0 ? (
            <div className="space-y-4">
              {users.map((member: OrganizationMember) => (
                <div
                  key={member.id}
                  className="flex items-center justify-between p-4 border border-gray-200 rounded-lg hover:bg-gray-50"
                >
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2">
                      {getRoleIcon(member.role)}
                      <div>
                        <div className="font-medium text-gray-900">
                          {member.user.name || member.user.email}
                        </div>
                        <div className="text-sm text-gray-500">{member.user.email}</div>
                      </div>
                    </div>
                    {getRoleBadge(member.role)}
                  </div>
                  <div className="flex items-center gap-2">
                    <select
                      value={member.role}
                      onChange={(e) =>
                        updateRoleMutation.mutate({
                          userId: member.user_id,
                          role: e.target.value as Role,
                        })
                      }
                      className="px-3 py-1 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                      disabled={updateRoleMutation.isPending}
                    >
                      <option value={Role.READER}>Reader</option>
                      <option value={Role.WRITER}>Writer</option>
                      <option value={Role.ADMIN}>Admin</option>
                    </select>
                    <button
                      onClick={() => {
                        if (confirm('Are you sure you want to remove this user?')) {
                          removeUserMutation.mutate(member.user_id)
                        }
                      }}
                      className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                      title="Remove user"
                    >
                      <Trash2 className="h-5 w-5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">No users found</div>
          )}
        </div>
      </div>

      {/* Invitations Section */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Mail className="h-5 w-5" />
            Pending Invitations
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
                  <div>
                    <div className="font-medium text-gray-900">{invitation.email}</div>
                    <div className="text-sm text-gray-500">
                      Role: {invitation.role} • Expires: {new Date(invitation.expires_at).toLocaleDateString()}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {getInvitationStatusBadge(invitation.status)}
                    {invitation.status === 'pending' && (
                      <button
                        onClick={() => {
                          if (confirm('Cancel this invitation?')) {
                            cancelInvitationMutation.mutate(invitation.id)
                          }
                        }}
                        className="p-2 text-gray-600 hover:bg-gray-50 rounded-lg transition-colors"
                        title="Cancel invitation"
                      >
                        <X className="h-5 w-5" />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">No pending invitations</div>
          )}
        </div>
      </div>

      {/* Invite Modal */}
      {showInviteModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Invite User</h3>
              <button
                onClick={() => setShowInviteModal(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleInvite} className="p-6 space-y-4">
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
                  Email Address
                </label>
                <input
                  id="email"
                  type="email"
                  required
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="user@example.com"
                />
              </div>
              <div>
                <label htmlFor="role" className="block text-sm font-medium text-gray-700 mb-1">
                  Role
                </label>
                <select
                  id="role"
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as Role)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  <option value={Role.READER}>Reader - View only</option>
                  <option value={Role.WRITER}>Writer - Create and edit</option>
                  <option value={Role.ADMIN}>Admin - Full access</option>
                </select>
              </div>
              <div className="flex gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowInviteModal(false)}
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={inviteMutation.isPending}
                  className="flex-1 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-50"
                >
                  {inviteMutation.isPending ? 'Sending...' : 'Send Invitation'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

