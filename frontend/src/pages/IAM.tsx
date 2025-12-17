import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useState } from 'react'
import { Role, Invitation, OrganizationMember, InvitationCreate } from '../types/api'
import { Users, Mail, UserPlus, Shield, ShieldCheck, ShieldAlert, X, Trash2 } from 'lucide-react'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'

export default function IAM() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showInviteModal, setShowInviteModal] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<Role>(Role.READER)
  const [showRemoveModal, setShowRemoveModal] = useState(false)
  const [memberToRemove, setMemberToRemove] = useState<OrganizationMember | null>(null)
  const [showCancelModal, setShowCancelModal] = useState(false)
  const [invitationToCancel, setInvitationToCancel] = useState<Invitation | null>(null)

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
      showToast('User role updated successfully', 'success')
    },
    onError: (error: any) => {
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to update user role'
      showToast(errorMessage, 'error')
    },
  })

  const removeUserMutation = useMutation({
    mutationFn: (userId: string) => apiClient.removeUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['iam', 'users'] })
      setShowRemoveModal(false)
      setMemberToRemove(null)
      showToast('User removed successfully', 'success')
    },
    onError: (error: any) => {
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to remove user'
      showToast(errorMessage, 'error')
      // Don't close modal on error so user can see the error message
    },
  })

  const handleRemoveClick = (member: OrganizationMember) => {
    setMemberToRemove(member)
    setShowRemoveModal(true)
  }

  const handleRemoveConfirm = () => {
    if (memberToRemove) {
      removeUserMutation.mutate(memberToRemove.user_id)
    }
  }

  const cancelInvitationMutation = useMutation({
    mutationFn: (invitationId: string) => apiClient.cancelInvitation(invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['iam', 'invitations'] })
      setShowCancelModal(false)
      setInvitationToCancel(null)
      showToast('Invitation cancelled successfully', 'success')
    },
    onError: (error: any) => {
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to cancel invitation'
      showToast(errorMessage, 'error')
    },
  })

  const handleCancelClick = (invitation: Invitation) => {
    setInvitationToCancel(invitation)
    setShowCancelModal(true)
  }

  const handleCancelConfirm = () => {
    if (invitationToCancel) {
      cancelInvitationMutation.mutate(invitationToCancel.id)
    }
  }

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
      <ToastContainer />
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Identity & Access Management</h1>
          <p className="mt-2 text-sm text-gray-600">
            Manage users and their permissions in your organization
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => setShowInviteModal(true)}
          leftIcon={<UserPlus className="h-5 w-5" />}
        >
          Invite User
        </Button>
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
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      User
                    </th>
                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Email
                    </th>
                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Role
                    </th>
                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Joined
                    </th>
                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {users.map((member: OrganizationMember) => (
                    <tr key={member.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center">
                          {getRoleIcon(member.role)}
                          <div className="ml-3">
                            <div className="text-sm font-medium text-gray-900">
                              {member.user.name || 'No name'}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm text-gray-900">{member.user.email}</div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <select
                          value={member.role}
                          onChange={(e) =>
                            updateRoleMutation.mutate({
                              userId: member.user_id,
                              role: e.target.value as Role,
                            })
                          }
                          className="px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                          disabled={updateRoleMutation.isPending}
                        >
                          <option value={Role.READER}>Reader</option>
                          <option value={Role.WRITER}>Writer</option>
                          <option value={Role.ADMIN}>Admin</option>
                        </select>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {new Date(member.joined_at).toLocaleDateString()}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRemoveClick(member)}
                          leftIcon={<Trash2 className="h-4 w-4" />}
                          title="Remove user"
                          className="text-red-600 hover:bg-red-50 hover:text-red-700"
                        >
                          Remove
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleCancelClick(invitation)}
                        leftIcon={<X className="h-5 w-5" />}
                        title="Cancel invitation"
                        className="text-gray-600 hover:bg-gray-50"
                      >
                        Cancel
                      </Button>
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
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setShowInviteModal(false)}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  isLoading={inviteMutation.isPending}
                  className="flex-1"
                >
                  Send Invitation
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Remove User Confirmation Modal */}
      {showRemoveModal && memberToRemove && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowRemoveModal(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Remove User</h3>
              <button
                onClick={() => {
                  setShowRemoveModal(false)
                  setMemberToRemove(null)
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6">
              <div className="flex items-start gap-4 mb-6">
                <div className="flex-shrink-0">
                  <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                    <Trash2 className="h-6 w-6 text-red-600" />
                  </div>
                </div>
                <div className="flex-1">
                  <p className="text-sm text-gray-700 mb-2">
                    Are you sure you want to remove <span className="font-semibold text-gray-900">{memberToRemove.user.name || memberToRemove.user.email}</span> from the organization?
                  </p>
                  <p className="text-xs text-gray-500">
                    This action cannot be undone. The user will lose access to all organization resources.
                  </p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowRemoveModal(false)
                    setMemberToRemove(null)
                  }}
                  disabled={removeUserMutation.isPending}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={handleRemoveConfirm}
                  isLoading={removeUserMutation.isPending}
                  leftIcon={!removeUserMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                  className="flex-1"
                >
                  Remove User
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Cancel Invitation Confirmation Modal */}
      {showCancelModal && invitationToCancel && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowCancelModal(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Cancel Invitation</h3>
              <button
                onClick={() => {
                  setShowCancelModal(false)
                  setInvitationToCancel(null)
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6">
              <div className="flex items-start gap-4 mb-6">
                <div className="flex-shrink-0">
                  <div className="w-12 h-12 rounded-full bg-yellow-100 flex items-center justify-center">
                    <X className="h-6 w-6 text-yellow-600" />
                  </div>
                </div>
                <div className="flex-1">
                  <p className="text-sm text-gray-700 mb-2">
                    Are you sure you want to cancel the invitation for <span className="font-semibold text-gray-900">{invitationToCancel.email}</span>?
                  </p>
                  <p className="text-xs text-gray-500">
                    This action cannot be undone. The invitation will be cancelled and the user will not be able to accept it.
                  </p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowCancelModal(false)
                    setInvitationToCancel(null)
                  }}
                  disabled={cancelInvitationMutation.isPending}
                  className="flex-1"
                >
                  Keep Invitation
                </Button>
                <Button
                  variant="danger"
                  onClick={handleCancelConfirm}
                  isLoading={cancelInvitationMutation.isPending}
                  leftIcon={!cancelInvitationMutation.isPending ? <X className="h-4 w-4" /> : undefined}
                  className="flex-1"
                >
                  Cancel Invitation
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

