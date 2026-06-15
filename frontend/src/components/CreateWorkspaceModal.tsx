import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, Plus, Trash2, Users, X } from 'lucide-react'
import { apiClient } from '../lib/api'
import type { OrganizationMember, Workspace, WorkspaceRole } from '../types/api'
import Button from './Button'
import { useToast } from '../hooks/useToast'
import { getApiErrorMessage } from '../lib/apiErrors'
import { useAuthStore } from '../store/authStore'

export interface PendingWorkspaceMember {
  user_id: string
  role_id: string
  user_email: string
  role_name: string
}

interface CreateWorkspaceModalProps {
  open: boolean
  onClose: () => void
  onCreated: (workspace: Workspace) => void | Promise<void>
}

export default function CreateWorkspaceModal({
  open,
  onClose,
  onCreated,
}: CreateWorkspaceModalProps) {
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [pendingMembers, setPendingMembers] = useState<PendingWorkspaceMember[]>([])
  const [selectedUserId, setSelectedUserId] = useState('')
  const [selectedRoleId, setSelectedRoleId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const { showToast, ToastContainer } = useToast()
  const currentUserId = useAuthStore((s) => s.user?.id ?? null)

  const { data: orgUsers = [] } = useQuery({
    queryKey: ['iam', 'users'],
    queryFn: () => apiClient.listOrganizationUsers(),
    enabled: open,
  })

  const { data: roles = [] } = useQuery({
    queryKey: ['workspace-roles'],
    queryFn: () => apiClient.listWorkspaceRoles(),
    enabled: open,
  })

  const pendingUserIds = useMemo(
    () => new Set(pendingMembers.map((m) => m.user_id)),
    [pendingMembers],
  )

  const availableUsers = useMemo(
    () =>
      orgUsers.filter(
        (u) => !pendingUserIds.has(u.user_id) && u.user_id !== currentUserId,
      ),
    [orgUsers, pendingUserIds, currentUserId],
  )

  const defaultRoleId = useMemo(() => {
    const viewer = roles.find((r) => r.name === 'Viewer')
    return viewer?.id ?? roles[0]?.id ?? ''
  }, [roles])

  const activeRoleId = selectedRoleId || defaultRoleId

  useEffect(() => {
    if (open && defaultRoleId && !selectedRoleId) {
      setSelectedRoleId(defaultRoleId)
    }
  }, [open, defaultRoleId, selectedRoleId])

  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [open])

  const resetForm = () => {
    setName('')
    setSlug('')
    setPendingMembers([])
    setSelectedUserId('')
    setSelectedRoleId('')
    setError('')
  }

  const handleClose = () => {
    if (submitting) return
    resetForm()
    onClose()
  }

  const handleAddMember = () => {
    if (!selectedUserId || !activeRoleId) {
      setError('Select a user and role to add.')
      return
    }
    const user = orgUsers.find((u) => u.user_id === selectedUserId)
    const role = roles.find((r) => r.id === activeRoleId)
    if (!user || !role) return

    setPendingMembers((prev) => [
      ...prev,
      {
        user_id: user.user_id,
        role_id: role.id,
        user_email: user.user.email,
        role_name: role.name,
      },
    ])
    setSelectedUserId('')
    setSelectedRoleId(defaultRoleId)
    setError('')
  }

  const handleAddAllMembers = () => {
    const role = roles.find((r) => r.id === activeRoleId)
    if (!role) {
      setError('Select a role before adding members.')
      return
    }
    if (availableUsers.length === 0) {
      setError('All org members are already in the list.')
      return
    }

    setPendingMembers((prev) => [
      ...prev,
      ...availableUsers.map((user: OrganizationMember) => ({
        user_id: user.user_id,
        role_id: role.id,
        user_email: user.user.email,
        role_name: role.name,
      })),
    ])
    setSelectedUserId('')
    setError('')
  }

  const handleRemoveMember = (userId: string) => {
    setPendingMembers((prev) => prev.filter((m) => m.user_id !== userId))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmedName = name.trim()
    if (!trimmedName) {
      setError('Workspace name is required.')
      return
    }

    setSubmitting(true)
    setError('')

    try {
      const created = await apiClient.createWorkspace({
        name: trimmedName,
        ...(slug.trim() ? { slug: slug.trim() } : {}),
      })

      const failures: string[] = []
      for (const member of pendingMembers) {
        try {
          await apiClient.addWorkspaceMember(created.id, {
            user_id: member.user_id,
            role_id: member.role_id,
          })
        } catch (memberErr: any) {
          const detail =
            memberErr?.response?.data?.detail ||
            `Could not add ${member.user_email}`
          failures.push(
            typeof detail === 'string' ? detail : `Could not add ${member.user_email}`,
          )
        }
      }

      resetForm()
      await onCreated(created)
      onClose()

      if (failures.length > 0) {
        showToast(
          `Workspace created, but some members could not be added: ${failures.join('; ')}`,
          'error',
        )
      } else {
        showToast('Workspace created', 'success')
      }
    } catch (err: unknown) {
      const message = getApiErrorMessage(err, 'Could not create workspace.')
      setError(message)
      showToast(message, 'error')
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 overflow-y-auto overflow-x-hidden">
      <ToastContainer />
      <div
        className="fixed inset-0 bg-gray-900/40 backdrop-blur-sm"
        onClick={handleClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-workspace-title"
        className="relative z-[10000] bg-white rounded-xl shadow-2xl w-full max-w-md max-h-[min(90vh,calc(100vh-2rem))] overflow-hidden flex flex-col min-w-0"
      >
        <div className="px-5 py-4 border-b border-gray-200 flex items-start justify-between gap-3 shrink-0">
          <div className="min-w-0">
            <h2
              id="create-workspace-title"
              className="text-lg font-semibold text-gray-900"
            >
              Create workspace
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Set a name and optionally invite org members.
            </p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            disabled={submitting}
            className="text-gray-400 hover:text-gray-600 p-1 shrink-0"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col flex-1 min-h-0 min-w-0">
          <div className="px-5 py-4 space-y-5 overflow-y-auto overflow-x-hidden flex-1 min-w-0">
            <div className="space-y-4">
              <div>
                <label
                  htmlFor="workspace-name"
                  className="block text-sm font-medium text-gray-700 mb-1"
                >
                  Name
                </label>
                <input
                  id="workspace-name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Project Phoenix"
                  className="w-full min-w-0 px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  autoFocus
                  disabled={submitting}
                />
              </div>

              <div>
                <label
                  htmlFor="workspace-slug"
                  className="block text-sm font-medium text-gray-700 mb-1"
                >
                  Slug <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <input
                  id="workspace-slug"
                  type="text"
                  value={slug}
                  onChange={(e) =>
                    setSlug(
                      e.target.value.toLowerCase().replace(/[^a-z0-9-_]/g, '_'),
                    )
                  }
                  placeholder="Derived from name if empty"
                  className="w-full min-w-0 px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  disabled={submitting}
                />
              </div>
            </div>

            <div className="border-t border-gray-100 pt-4 space-y-3 min-w-0">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Members
                </label>
                <p className="text-xs text-gray-500 mt-0.5">
                  You are added automatically as Workspace Admin.
                </p>
              </div>

              <div className="space-y-2 min-w-0">
                <select
                  value={selectedUserId}
                  onChange={(e) => setSelectedUserId(e.target.value)}
                  className="w-full min-w-0 px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  disabled={submitting || availableUsers.length === 0}
                >
                  <option value="">Select org member…</option>
                  {availableUsers.map((u: OrganizationMember) => (
                    <option key={u.user_id} value={u.user_id}>
                      {u.user.email}
                      {u.user.name ? ` (${u.user.name})` : ''}
                    </option>
                  ))}
                </select>

                <select
                  value={activeRoleId}
                  onChange={(e) => setSelectedRoleId(e.target.value)}
                  className="w-full min-w-0 px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  disabled={submitting || roles.length === 0}
                >
                  {roles.map((r: WorkspaceRole) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>

                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleAddMember}
                  disabled={submitting || !selectedUserId}
                  leftIcon={<Plus className="h-4 w-4" />}
                  className="w-full"
                >
                  Add member
                </Button>

                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={handleAddAllMembers}
                  disabled={submitting || availableUsers.length === 0 || !activeRoleId}
                  leftIcon={<Users className="h-4 w-4" />}
                  className="w-full"
                >
                  Add all org members
                  {availableUsers.length > 0 ? ` (${availableUsers.length})` : ''}
                </Button>
              </div>

              {pendingMembers.length === 0 ? (
                <p className="text-sm text-gray-500">
                  No additional members yet. You can add them now or later from
                  Workspace Members settings.
                </p>
              ) : (
                <ul className="border border-gray-200 rounded-lg divide-y divide-gray-100 min-w-0">
                  {pendingMembers.map((member) => (
                    <li
                      key={member.user_id}
                      className="flex items-center justify-between gap-2 px-3 py-2 text-sm min-w-0"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="font-medium text-gray-900 truncate">
                          {member.user_email}
                        </div>
                        <div className="text-xs text-gray-500 truncate">
                          {member.role_name}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRemoveMember(member.user_id)}
                        disabled={submitting}
                        className="text-red-600 hover:text-red-800 p-1 shrink-0"
                        title="Remove"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {error && (
              <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2 break-words">
                {error}
              </div>
            )}
          </div>

          <div className="px-5 py-4 border-t border-gray-200 flex flex-col-reverse sm:flex-row gap-2 sm:justify-end bg-gray-50 shrink-0">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              disabled={submitting}
              className="w-full sm:w-auto"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={submitting || !name.trim()}
              isLoading={submitting}
              leftIcon={
                submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : undefined
              }
              className="w-full sm:w-auto"
            >
              Create workspace
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  )
}
