import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, FolderKanban, Plus } from 'lucide-react'
import { apiClient } from '../lib/api'
import type { Workspace } from '../types/api'
import { useCanWrite } from '../hooks/useRole'
import { useWorkspaceStore } from '../store/workspaceStore'
import CreateWorkspaceModal from './CreateWorkspaceModal'

export default function WorkspaceSwitcher() {
  const queryClient = useQueryClient()
  const canWrite = useCanWrite()
  const activeId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const switchWorkspace = useWorkspaceStore((s) => s.switchWorkspace)
  const setActiveCapabilities = useWorkspaceStore((s) => s.setActiveCapabilities)
  const [open, setOpen] = useState(false)
  const [showCreateModal, setShowCreateModal] = useState(false)

  const {
    data: workspaces = [],
    isLoading,
    refetch,
  } = useQuery<Workspace[]>({
    queryKey: ['workspaces'],
    queryFn: () => apiClient.listWorkspaces(),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (!workspaces.length) return
    const stored = activeId
    const isValid = stored && workspaces.some((w) => w.id === stored)
    const fallback =
      (isValid ? workspaces.find((w) => w.id === stored) : null) ??
      workspaces.find((w) => w.is_default) ??
      workspaces[0]

    if (!fallback) return

    if (!isValid) {
      switchWorkspace(fallback.id, fallback.capabilities ?? [])
      queryClient.invalidateQueries()
      return
    }

    const current = workspaces.find((w) => w.id === stored)
    if (!current) return

    const nextCaps = current.capabilities ?? []
    const { activeCapabilities } = useWorkspaceStore.getState()
    const capsChanged =
      nextCaps.length !== activeCapabilities.length ||
      nextCaps.some((cap, i) => cap !== activeCapabilities[i])

    if (capsChanged) {
      setActiveCapabilities(nextCaps)
    }
  }, [workspaces, activeId, queryClient, switchWorkspace, setActiveCapabilities])

  const activeWorkspace = useMemo(
    () => workspaces.find((w) => w.id === activeId) ?? null,
    [workspaces, activeId],
  )

  const handleSelect = async (workspace: Workspace) => {
    if (workspace.id === activeId) {
      setOpen(false)
      return
    }
    switchWorkspace(workspace.id, workspace.capabilities ?? [])
    setOpen(false)
    await queryClient.invalidateQueries()
  }

  const handleWorkspaceCreated = async (created: Workspace) => {
    await refetch()
    setOpen(false)
    await handleSelect(created)
  }

  const openCreateModal = () => {
    setOpen(false)
    setShowCreateModal(true)
  }

  return (
    <>
      <div className="relative">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 hover:border-gray-300 transition-all shadow-sm"
          title="Switch workspace"
        >
          <FolderKanban className="h-4 w-4 text-gray-500 flex-shrink-0" />
          <span className="truncate flex-1 text-left">
            {isLoading
              ? 'Loading workspaces…'
              : activeWorkspace?.name ?? 'Select workspace'}
          </span>
          <ChevronDown className="h-4 w-4 text-gray-500 flex-shrink-0" />
        </button>

        {open && (
          <>
            <div
              className="fixed inset-0 z-10"
              onClick={() => setOpen(false)}
            />
            <div className="absolute left-0 right-0 mt-2 bg-white rounded-lg shadow-lg border border-gray-200 z-20">
              <div className="px-4 py-2 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center justify-between">
                <span>Workspaces</span>
                {canWrite && (
                  <button
                    type="button"
                    onClick={openCreateModal}
                    className="text-primary-600 hover:text-primary-700 normal-case font-medium flex items-center gap-1"
                  >
                    <Plus className="h-3 w-3" /> New
                  </button>
                )}
              </div>

              <div className="max-h-80 overflow-y-auto py-1">
                {workspaces.length === 0 && !isLoading && (
                  <div className="px-4 py-3 text-sm text-gray-500">
                    No workspaces available.
                    {canWrite && (
                      <button
                        type="button"
                        onClick={openCreateModal}
                        className="block mt-2 text-primary-600 hover:text-primary-700 font-medium"
                      >
                        Create your first workspace
                      </button>
                    )}
                  </div>
                )}
                {workspaces.map((ws) => {
                  const isCurrent = ws.id === activeId
                  return (
                    <button
                      key={ws.id}
                      type="button"
                      onClick={() => handleSelect(ws)}
                      className={`w-full px-4 py-2.5 text-left hover:bg-gray-50 transition-colors flex items-center justify-between gap-2 ${
                        isCurrent ? 'bg-primary-50' : ''
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-gray-900 truncate">
                          {ws.name}
                          {ws.is_default && (
                            <span className="ml-2 text-xs font-normal text-gray-500">
                              (default)
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-gray-500 truncate">
                          {ws.role_name ? `${ws.role_name} · ${ws.slug}` : ws.slug}
                        </div>
                      </div>
                      {isCurrent && (
                        <Check className="h-4 w-4 text-primary-600 flex-shrink-0" />
                      )}
                    </button>
                  )
                })}
              </div>
            </div>
          </>
        )}
      </div>

      <CreateWorkspaceModal
        open={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onCreated={handleWorkspaceCreated}
      />
    </>
  )
}
