import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Trash2, UserPlus, Users } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { useWorkspaceCapabilities } from '../../hooks/useWorkspaceCapabilities'
import { useWorkspaceStore } from '../../store/workspaceStore'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'

export default function WorkspaceMembers() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const { canViewMembers, canManageMembers } = useWorkspaceCapabilities()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const [showAdd, setShowAdd] = useState(false)
  const [selectedUserId, setSelectedUserId] = useState('')
  const [selectedRoleId, setSelectedRoleId] = useState('')

  const { data: members = [], isLoading } = useQuery({
    queryKey: ['workspace-members', activeWorkspaceId],
    queryFn: () => apiClient.listWorkspaceMembers(activeWorkspaceId!),
    enabled: Boolean(activeWorkspaceId) && canViewMembers,
  })

  const { data: orgUsers = [] } = useQuery({
    queryKey: ['iam', 'users'],
    queryFn: () => apiClient.listOrganizationUsers(),
    enabled: canManageMembers,
  })

  const { data: roles = [] } = useQuery({
    queryKey: ['workspace-roles'],
    queryFn: () => apiClient.listWorkspaceRoles(),
  })

  const addMutation = useMutation({
    mutationFn: () =>
      apiClient.addWorkspaceMember(activeWorkspaceId!, {
        user_id: selectedUserId,
        role_id: selectedRoleId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-members'] })
      setShowAdd(false)
      setSelectedUserId('')
      setSelectedRoleId('')
      showToast('Member added', 'success')
    },
    onError: (error: any) => {
      showToast(error.response?.data?.detail || 'Failed to add member', 'error')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ userId, roleId }: { userId: string; roleId: string }) =>
      apiClient.updateWorkspaceMember(activeWorkspaceId!, userId, {
        role_id: roleId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-members'] })
      showToast('Role updated', 'success')
    },
  })

  const removeMutation = useMutation({
    mutationFn: (userId: string) =>
      apiClient.removeWorkspaceMember(activeWorkspaceId!, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-members'] })
      showToast('Member removed', 'success')
    },
  })

  if (!activeWorkspaceId) {
    return (
      <div className="p-6 text-gray-600">
        Select a workspace from the sidebar to manage members.
      </div>
    )
  }

  if (!canViewMembers) {
    return (
      <div className="p-6 text-gray-600">
        You do not have permission to view workspace members.
      </div>
    )
  }

  const memberUserIds = new Set(members.map((m) => m.user_id))
  const availableUsers = orgUsers.filter((u) => !memberUserIds.has(u.user_id))

  return (
    <div className="p-6 max-w-4xl">
      <ToastContainer />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 flex items-center gap-2">
            <Users className="h-6 w-6" />
            Workspace Members
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage who can access the active workspace and their roles.
          </p>
        </div>
        {canManageMembers && (
          <Button onClick={() => setShowAdd((v) => !v)}>
            <UserPlus className="h-4 w-4 mr-2" />
            Add member
          </Button>
        )}
      </div>

      {showAdd && canManageMembers && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50 space-y-3">
          <select
            value={selectedUserId}
            onChange={(e) => setSelectedUserId(e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
          >
            <option value="">Select org member…</option>
            {availableUsers.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.user?.email ?? u.user_id}
              </option>
            ))}
          </select>
          <select
            value={selectedRoleId}
            onChange={(e) => setSelectedRoleId(e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
          >
            <option value="">Select role…</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
          <Button
            disabled={!selectedUserId || !selectedRoleId || addMutation.isPending}
            onClick={() => addMutation.mutate()}
          >
            Add to workspace
          </Button>
        </div>
      )}

      {isLoading ? (
        <div className="text-gray-500">Loading members…</div>
      ) : (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  User
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Role
                </th>
                {canManageMembers && <th className="px-4 py-3" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {members.map((member) => (
                <tr key={member.id}>
                  <td className="px-4 py-3 text-sm">
                    <div className="font-medium text-gray-900">{member.user_email}</div>
                    {member.user_name && (
                      <div className="text-gray-500">{member.user_name}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {canManageMembers ? (
                      <select
                        value={member.role_id}
                        onChange={(e) =>
                          updateMutation.mutate({
                            userId: member.user_id,
                            roleId: e.target.value,
                          })
                        }
                        className="px-2 py-1 border border-gray-200 rounded text-sm"
                      >
                        {roles.map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      member.role_name
                    )}
                  </td>
                  {canManageMembers && (
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => removeMutation.mutate(member.user_id)}
                        className="text-red-600 hover:text-red-800"
                        title="Remove member"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 text-sm text-gray-500">
        Org admins can also manage{' '}
        <Link to="/iam" className="text-primary-600 hover:underline">
          workspace roles
        </Link>{' '}
        under IAM settings.
      </p>
    </div>
  )
}
