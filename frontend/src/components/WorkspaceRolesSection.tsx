import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { ChevronDown, Pencil, Plus, Trash2, X } from 'lucide-react'
import { apiClient } from '../lib/api'
import { getApiErrorMessage } from '../lib/apiErrors'
import type { CapabilityDomain, CapabilityInfo, WorkspaceRole } from '../types/api'
import Button from './Button'
import { useToast } from '../hooks/useToast'

function buildCapabilityLabelMap(domains: CapabilityDomain[]): Map<string, string> {
  const map = new Map<string, string>()
  for (const domain of domains) {
    for (const cap of domain.capabilities) {
      map.set(cap.key, cap.label)
    }
  }
  return map
}

export default function WorkspaceRolesSection() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showCreate, setShowCreate] = useState(false)
  const [expandedRoleIds, setExpandedRoleIds] = useState<Set<string>>(new Set())
  const [editingRoleId, setEditingRoleId] = useState<string | null>(null)

  const { data: roles = [], isLoading: rolesLoading, error: rolesError } = useQuery({
    queryKey: ['workspace-roles'],
    queryFn: () => apiClient.listWorkspaceRoles(),
  })

  const { data: domains = [] } = useQuery({
    queryKey: ['capabilities'],
    queryFn: () => apiClient.listCapabilities(),
  })

  const capLabels = useMemo(() => buildCapabilityLabelMap(domains), [domains])

  const createMutation = useMutation({
    mutationFn: (payload: { name: string; description?: string; capabilities: string[] }) =>
      apiClient.createWorkspaceRole(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-roles'] })
      setShowCreate(false)
      showToast('Role created', 'success')
    },
    onError: (error: unknown) => {
      showToast(getApiErrorMessage(error, 'Failed to create role'), 'error')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      roleId,
      payload,
    }: {
      roleId: string
      payload: { name?: string; description?: string | null; capabilities?: string[] }
    }) => apiClient.updateWorkspaceRole(roleId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-roles'] })
      setEditingRoleId(null)
      showToast('Role updated', 'success')
    },
    onError: (error: unknown) => {
      showToast(getApiErrorMessage(error, 'Failed to update role'), 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (roleId: string) => apiClient.deleteWorkspaceRole(roleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-roles'] })
      setEditingRoleId(null)
      showToast('Role deleted', 'success')
    },
    onError: (error: unknown) => {
      showToast(getApiErrorMessage(error, 'Failed to delete role'), 'error')
    },
  })

  const systemRoles = useMemo(
    () => roles.filter((r: WorkspaceRole) => r.is_system),
    [roles],
  )
  const customRoles = useMemo(
    () => roles.filter((r: WorkspaceRole) => !r.is_system),
    [roles],
  )

  const toggleExpanded = (roleId: string) => {
    setExpandedRoleIds((prev) => {
      const next = new Set(prev)
      if (next.has(roleId)) next.delete(roleId)
      else next.add(roleId)
      return next
    })
  }

  const startEdit = (role: WorkspaceRole) => {
    setEditingRoleId(role.id)
    setExpandedRoleIds((prev) => new Set(prev).add(role.id))
    setShowCreate(false)
  }

  return (
    <div>
      <ToastContainer />
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Workspace Roles</h2>
          <p className="text-sm text-gray-500">
            System roles are predefined. Org admins can create custom roles from capabilities.
          </p>
        </div>
        <Button
          onClick={() => {
            setShowCreate((v) => !v)
            setEditingRoleId(null)
          }}
        >
          <Plus className="h-4 w-4 mr-2" />
          Custom role
        </Button>
      </div>

      {rolesError && (
        <div className="mb-4 text-sm text-red-600">
          {getApiErrorMessage(rolesError, 'Failed to load workspace roles')}
        </div>
      )}

      {showCreate && (
        <RoleForm
          title="Create custom role"
          domains={domains}
          submitLabel="Create role"
          isPending={createMutation.isPending}
          onCancel={() => setShowCreate(false)}
          onSubmit={(values) => createMutation.mutate(values)}
        />
      )}

      {rolesLoading ? (
        <div className="text-sm text-gray-500 py-4">Loading roles…</div>
      ) : (
        <>
          <RoleList
            title="System roles"
            emptyMessage="No system roles found."
            roles={systemRoles}
            domains={domains}
            capLabels={capLabels}
            expandedRoleIds={expandedRoleIds}
            editingRoleId={editingRoleId}
            onToggleExpand={toggleExpanded}
          />
          <RoleList
            title="Custom roles"
            emptyMessage="No custom roles yet. Create one to define a capability bundle for your team."
            roles={customRoles}
            domains={domains}
            capLabels={capLabels}
            expandedRoleIds={expandedRoleIds}
            editingRoleId={editingRoleId}
            onToggleExpand={toggleExpanded}
            onEdit={startEdit}
            onDelete={(id) => deleteMutation.mutate(id)}
            onCancelEdit={() => setEditingRoleId(null)}
            onSaveEdit={(roleId, values) => updateMutation.mutate({ roleId, payload: values })}
            isSaving={updateMutation.isPending}
          />
        </>
      )}
    </div>
  )
}

function RoleList({
  title,
  emptyMessage,
  roles,
  domains,
  capLabels,
  expandedRoleIds,
  editingRoleId,
  onToggleExpand,
  onEdit,
  onDelete,
  onCancelEdit,
  onSaveEdit,
  isSaving,
}: {
  title: string
  emptyMessage: string
  roles: WorkspaceRole[]
  domains: CapabilityDomain[]
  capLabels: Map<string, string>
  expandedRoleIds: Set<string>
  editingRoleId: string | null
  onToggleExpand: (roleId: string) => void
  onEdit?: (role: WorkspaceRole) => void
  onDelete?: (id: string) => void
  onCancelEdit?: () => void
  onSaveEdit?: (
    roleId: string,
    values: { name: string; description?: string; capabilities: string[] },
  ) => void
  isSaving?: boolean
}) {
  return (
    <div className="mb-6">
      <h3 className="text-sm font-medium text-gray-700 mb-2">{title}</h3>
      {!roles.length ? (
        <div className="text-sm text-gray-500 border border-dashed border-gray-200 rounded-lg p-4">
          {emptyMessage}
        </div>
      ) : (
        <div className="space-y-2">
          {roles.map((role) => {
            const expanded = expandedRoleIds.has(role.id)
            const isEditing = editingRoleId === role.id

            return (
              <div
                key={role.id}
                className="border border-gray-200 rounded-lg bg-white overflow-hidden"
              >
                <div className="flex items-start justify-between p-3 gap-3">
                  <button
                    type="button"
                    onClick={() => onToggleExpand(role.id)}
                    className="flex items-start gap-2 text-left min-w-0 flex-1"
                  >
                    <ChevronDown
                      className={`h-4 w-4 mt-1 shrink-0 text-gray-400 transition-transform ${
                        expanded ? 'rotate-180' : ''
                      }`}
                    />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-gray-900">{role.name}</span>
                        {role.is_system && (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
                            System
                          </span>
                        )}
                      </div>
                      {role.description && (
                        <div className="text-sm text-gray-500">{role.description}</div>
                      )}
                      <div className="text-xs text-gray-400 mt-1">
                        {role.capabilities.length} capabilities
                      </div>
                    </div>
                  </button>

                  <div className="flex items-center gap-1 shrink-0">
                    {onEdit && !isEditing && (
                      <button
                        type="button"
                        onClick={() => onEdit(role)}
                        className="p-1.5 text-gray-500 hover:text-primary-600 rounded"
                        title="Edit role"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                    )}
                    {onDelete && !isEditing && (
                      <button
                        type="button"
                        onClick={() => onDelete(role.id)}
                        className="p-1.5 text-red-600 hover:text-red-800 rounded"
                        title="Delete role"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </div>

                {expanded && !isEditing && (
                  <CapabilityDetails
                    role={role}
                    domains={domains}
                    capLabels={capLabels}
                  />
                )}

                {expanded && isEditing && onCancelEdit && onSaveEdit && (
                  <div className="border-t border-gray-100 p-3 bg-gray-50">
                    <RoleForm
                      key={role.id}
                      title="Edit role"
                      initialName={role.name}
                      initialDescription={role.description ?? ''}
                      initialCapabilities={role.capabilities}
                      domains={domains}
                      submitLabel="Save changes"
                      isPending={Boolean(isSaving)}
                      onCancel={onCancelEdit}
                      onSubmit={(values) => onSaveEdit(role.id, values)}
                    />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function CapabilityDetails({
  role,
  domains,
  capLabels,
}: {
  role: WorkspaceRole
  domains: CapabilityDomain[]
  capLabels: Map<string, string>
}) {
  const assigned = new Set(role.capabilities)

  return (
    <div className="border-t border-gray-100 px-3 pb-3 pt-2 bg-gray-50 space-y-3">
      {domains.map((domain) => {
        const domainCaps = domain.capabilities.filter((cap) => assigned.has(cap.key))
        if (!domainCaps.length) return null

        return (
          <div key={domain.key}>
            <div className="text-xs font-semibold text-gray-500 uppercase mb-1">
              {domain.label}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {domainCaps.map((cap) => (
                <span
                  key={cap.key}
                  className="inline-flex px-2 py-0.5 rounded border border-primary-200 bg-primary-50 text-primary-800 text-xs"
                >
                  {capLabels.get(cap.key) ?? cap.label}
                </span>
              ))}
            </div>
          </div>
        )
      })}
      {role.capabilities.length === 0 && (
        <div className="text-sm text-gray-500">No capabilities assigned.</div>
      )}
    </div>
  )
}

function RoleForm({
  title,
  initialName = '',
  initialDescription = '',
  initialCapabilities = [],
  domains,
  submitLabel,
  isPending,
  onSubmit,
  onCancel,
}: {
  title: string
  initialName?: string
  initialDescription?: string
  initialCapabilities?: string[]
  domains: CapabilityDomain[]
  submitLabel: string
  isPending: boolean
  onSubmit: (values: { name: string; description?: string; capabilities: string[] }) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(initialName)
  const [description, setDescription] = useState(initialDescription)
  const [selectedCaps, setSelectedCaps] = useState<Set<string>>(
    () => new Set(initialCapabilities),
  )

  const toggleCap = (cap: string) => {
    setSelectedCaps((prev) => {
      const next = new Set(prev)
      if (next.has(cap)) next.delete(cap)
      else next.add(cap)
      return next
    })
  }

  return (
    <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50 space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-gray-900">{title}</h4>
        <button
          type="button"
          onClick={onCancel}
          className="text-gray-400 hover:text-gray-600"
          aria-label="Close form"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Role name"
        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
      />
      <input
        type="text"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description (optional)"
        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
      />
      <CapabilityPicker domains={domains} selected={selectedCaps} onToggle={toggleCap} />
      <div className="flex gap-2">
        <Button
          disabled={!name.trim() || selectedCaps.size === 0 || isPending}
          onClick={() =>
            onSubmit({
              name: name.trim(),
              description: description.trim() || undefined,
              capabilities: Array.from(selectedCaps),
            })
          }
        >
          {submitLabel}
        </Button>
        <Button variant="secondary" onClick={onCancel} disabled={isPending}>
          Cancel
        </Button>
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
