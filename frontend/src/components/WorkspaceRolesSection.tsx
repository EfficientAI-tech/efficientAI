import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { apiClient } from '../lib/api'
import type { CapabilityDomain, CapabilityInfo, WorkspaceRole } from '../types/api'
import Button from './Button'
import { useToast } from '../hooks/useToast'

export default function WorkspaceRolesSection() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [selectedCaps, setSelectedCaps] = useState<Set<string>>(new Set())

  const { data: roles = [] } = useQuery({
    queryKey: ['workspace-roles'],
    queryFn: () => apiClient.listWorkspaceRoles(),
  })

  const { data: domains = [] } = useQuery({
    queryKey: ['capabilities'],
    queryFn: () => apiClient.listCapabilities(),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      apiClient.createWorkspaceRole({
        name,
        description: description || undefined,
        capabilities: Array.from(selectedCaps),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-roles'] })
      setShowCreate(false)
      setName('')
      setDescription('')
      setSelectedCaps(new Set())
      showToast('Role created', 'success')
    },
    onError: (error: any) => {
      showToast(error.response?.data?.detail || 'Failed to create role', 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (roleId: string) => apiClient.deleteWorkspaceRole(roleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-roles'] })
      showToast('Role deleted', 'success')
    },
    onError: (error: any) => {
      showToast(error.response?.data?.detail || 'Failed to delete role', 'error')
    },
  })

  const toggleCap = (cap: string) => {
    setSelectedCaps((prev) => {
      const next = new Set(prev)
      if (next.has(cap)) next.delete(cap)
      else next.add(cap)
      return next
    })
  }

  const systemRoles = useMemo(
    () => roles.filter((r: WorkspaceRole) => r.is_system),
    [roles],
  )
  const customRoles = useMemo(
    () => roles.filter((r: WorkspaceRole) => !r.is_system),
    [roles],
  )

  return (
    <div className="mt-10 border-t border-gray-200 pt-8">
      <ToastContainer />
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Workspace Roles</h2>
          <p className="text-sm text-gray-500">
            System roles are predefined. Org admins can create custom roles from capabilities.
          </p>
        </div>
        <Button onClick={() => setShowCreate((v) => !v)}>
          <Plus className="h-4 w-4 mr-2" />
          Custom role
        </Button>
      </div>

      {showCreate && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50 space-y-4">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Role name"
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
          />
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
          />
          <CapabilityPicker
            domains={domains}
            selected={selectedCaps}
            onToggle={toggleCap}
          />
          <Button
            disabled={!name.trim() || selectedCaps.size === 0 || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Create role
          </Button>
        </div>
      )}

      <RoleList title="System roles" roles={systemRoles} />
      <RoleList
        title="Custom roles"
        roles={customRoles}
        onDelete={(id) => deleteMutation.mutate(id)}
      />
    </div>
  )
}

function RoleList({
  title,
  roles,
  onDelete,
}: {
  title: string
  roles: WorkspaceRole[]
  onDelete?: (id: string) => void
}) {
  if (!roles.length) return null
  return (
    <div className="mb-6">
      <h3 className="text-sm font-medium text-gray-700 mb-2">{title}</h3>
      <div className="space-y-2">
        {roles.map((role) => (
          <div
            key={role.id}
            className="flex items-start justify-between p-3 border border-gray-200 rounded-lg bg-white"
          >
            <div>
              <div className="font-medium text-gray-900">{role.name}</div>
              {role.description && (
                <div className="text-sm text-gray-500">{role.description}</div>
              )}
              <div className="text-xs text-gray-400 mt-1">
                {role.capabilities.length} capabilities
              </div>
            </div>
            {onDelete && (
              <button
                type="button"
                onClick={() => onDelete(role.id)}
                className="text-red-600 hover:text-red-800"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function CapabilityPicker({
  domains,
  selected,
  onToggle,
}: {
  domains: CapabilityDomain[]
  selected: Set<string>
  onToggle: (cap: string) => void
}) {
  return (
    <div className="space-y-3">
      {domains.map((domain) => (
        <div key={domain.key}>
          <div className="text-xs font-semibold text-gray-500 uppercase mb-1">
            {domain.label}
          </div>
          <div className="flex flex-wrap gap-2">
            {domain.capabilities.map((cap: CapabilityInfo) => (
              <label
                key={cap.key}
                className={`inline-flex items-center gap-1 px-2 py-1 rounded border text-xs cursor-pointer ${
                  selected.has(cap.key)
                    ? 'border-primary-500 bg-primary-50 text-primary-800'
                    : 'border-gray-200 bg-white text-gray-700'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selected.has(cap.key)}
                  onChange={() => onToggle(cap.key)}
                  className="sr-only"
                />
                {cap.label}
              </label>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
