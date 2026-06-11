import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, FolderKanban, Trash2, UserPlus, Users } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { useWorkspaceStore } from '../../store/workspaceStore'
import Button from '../Button'
import { useToast } from '../../hooks/useToast'

function workspaceCaps(caps: string[] | undefined) {
  const list = caps ?? []
  return {
    canViewMembers: list.includes('workspace.members.view'),
    canManageMembers: list.includes('workspace.members.manage'),
  }
}

export default function WorkspaceMembersSection() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [selectedUserId, setSelectedUserId] = useState('')
  const [selectedRoleId, setSelectedRoleId] = useState('')

  const { data: workspaces = [], isLoading: workspacesLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => apiClient.listWorkspaces(),
  })

  useEffect(() => {
    if (!workspaces.length) return
    const stillValid =
      selectedWorkspaceId && workspaces.some((w) => w.id === selectedWorkspaceId)
    if (stillValid) return

    const fallback =
      workspaces.find((w) => w.id === activeWorkspaceId) ?? workspaces[0]
    setSelectedWorkspaceId(fallback.id)
  }, [workspaces, activeWorkspaceId, selectedWorkspaceId])

  const selectedWorkspace = useMemo(
    () => workspaces.find((w) => w.id === selectedWorkspaceId) ?? null,
    [workspaces, selectedWorkspaceId],
  )

  const { canViewMembers, canManageMembers } = workspaceCaps(
    selectedWorkspace?.capabilities,
  )

  const { data: members = [], isLoading: membersLoading } = useQuery({
    queryKey: ['workspace-members', selectedWorkspaceId],
    queryFn: () => apiClient.listWorkspaceMembers(selectedWorkspaceId!),
    enabled: Boolean(selectedWorkspaceId) && canViewMembers,
  })

  const { data: orgUsers = [] } = useQuery({
    queryKey: ['iam', 'users'],
    queryFn: () => apiClient.listOrganizationUsers(),
    enabled: canManageMembers,
  })

  const { data: roles = [] } = useQuery({
    queryKey: ['workspace-roles'],
    queryFn: () => apiClient.listWorkspaceRoles(),
    enabled: canViewMembers,
  })

  const addMutation = useMutation({
    mutationFn: () =>
      apiClient.addWorkspaceMember(selectedWorkspaceId!, {
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
      apiClient.updateWorkspaceMember(selectedWorkspaceId!, userId, {
        role_id: roleId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-members'] })
      showToast('Role updated', 'success')
    },
  })

  const removeMutation = useMutation({
    mutationFn: (userId: string) =>
      apiClient.removeWorkspaceMember(selectedWorkspaceId!, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-members'] })
      showToast('Member removed', 'success')
    },
  })

  const memberUserIds = new Set(members.map((m) => m.user_id))
  const availableUsers = orgUsers.filter((u) => !memberUserIds.has(u.user_id))

  return (
    <div className="bg-white shadow rounded-lg">
      <ToastContainer />
      <div className="px-6 py-4 border-b border-gray-200 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Users className="h-5 w-5" />
            Workspace Members
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            Choose a workspace to view members and assign workspace roles.
          </p>
        </div>
        {canManageMembers && (
          <Button onClick={() => setShowAdd((v) => !v)}>
            <UserPlus className="h-4 w-4 mr-2" />
            Add member
          </Button>
        )}
      </div>

      <div className="p-6 space-y-6">
        <div>
          <label
            htmlFor="iam-workspace-select"
            className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-2"
          >
            Workspace
          </label>
          <div className="relative max-w-md">
            <FolderKanban className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            <select
              id="iam-workspace-select"
              value={selectedWorkspaceId ?? ''}
              onChange={(e) => {
                setSelectedWorkspaceId(e.target.value)
                setShowAdd(false)
              }}
              disabled={workspacesLoading || workspaces.length === 0}
              className="w-full appearance-none pl-10 pr-10 py-2.5 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:bg-gray-50 disabled:text-gray-500"
            >
              {workspaces.length === 0 && (
                <option value="">No workspaces available</option>
              )}
              {workspaces.map((ws) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name}
                  {ws.is_default ? ' (default)' : ''}
                  {ws.role_name ? ` · your role: ${ws.role_name}` : ''}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
          </div>
          {selectedWorkspace && (
            <p className="mt-2 text-xs text-gray-500">
              Slug: <span className="font-mono">{selectedWorkspace.slug}</span>
              {selectedWorkspace.role_name && (
                <>
                  {' '}
                  · Your role:{' '}
                  <span className="font-medium text-gray-700">
                    {selectedWorkspace.role_name}
                  </span>
                </>
              )}
            </p>
          )}
        </div>

        {!selectedWorkspaceId ? (
          <div className="text-center py-8 text-gray-500">
            {workspacesLoading ? 'Loading workspaces…' : 'Select a workspace.'}
          </div>
        ) : !canViewMembers ? (
          <div className="text-center py-8 text-gray-500">
            You do not have permission to view members for this workspace.
          </div>
        ) : (
          <>
            {showAdd && canManageMembers && (
              <div className="p-4 border border-gray-200 rounded-lg bg-gray-50 space-y-3">
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
                  disabled={
                    !selectedUserId || !selectedRoleId || addMutation.isPending
                  }
                  onClick={() => addMutation.mutate()}
                >
                  Add to workspace
                </Button>
              </div>
            )}

            {membersLoading ? (
              <div className="text-center py-8 text-gray-500">
                Loading members…
              </div>
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
                    {members.length === 0 ? (
                      <tr>
                        <td
                          colSpan={canManageMembers ? 3 : 2}
                          className="px-4 py-8 text-center text-sm text-gray-500"
                        >
                          No members in this workspace yet.
                        </td>
                      </tr>
                    ) : (
                      members.map((member) => (
                        <tr key={member.id}>
                          <td className="px-4 py-3 text-sm">
                            <div className="font-medium text-gray-900">
                              {member.user_email}
                            </div>
                            {member.user_name && (
                              <div className="text-gray-500">
                                {member.user_name}
                              </div>
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
                                onClick={() =>
                                  removeMutation.mutate(member.user_id)
                                }
                                className="text-red-600 hover:text-red-800"
                                title="Remove member"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </td>
                          )}
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
