import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { Check, ChevronDown, Copy, FolderKanban, Plus } from 'lucide-react'
import { apiClient } from '../lib/api'
import { copyTextToClipboard } from '../lib/clipboard'
import { resolveWorkspaceSwitchPath } from '../lib/workspaceNavigation'
import type { Workspace } from '../types/api'
import { useCanWrite } from '../hooks/useRole'
import { useWorkspaceStore } from '../store/workspaceStore'
import CreateWorkspaceModal from './CreateWorkspaceModal'

export default function WorkspaceSwitcher() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const canWrite = useCanWrite()
  const activeId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const switchWorkspace = useWorkspaceStore((s) => s.switchWorkspace)
  const setActiveCapabilities = useWorkspaceStore((s) => s.setActiveCapabilities)
  const [open, setOpen] = useState(false)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const onWorkspaceChanged = useCallback(
    async (workspace: Workspace) => {
      switchWorkspace(workspace.id, workspace.capabilities ?? [])
      const target = resolveWorkspaceSwitchPath(location.pathname)
      if (target) {
        navigate(target, { replace: true })
      }
      await queryClient.invalidateQueries()
    },
    [switchWorkspace, location.pathname, navigate, queryClient],
  )

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
    const activeWorkspaces = workspaces.filter((w) => w.is_active)
    const selectable = activeWorkspaces.length > 0 ? activeWorkspaces : workspaces
    const isValid = stored && selectable.some((w) => w.id === stored)
    const fallback =
      (isValid ? selectable.find((w) => w.id === stored) : null) ??
      selectable.find((w) => w.is_default) ??
      selectable[0]

    if (!fallback) return

    if (!isValid) {
      void onWorkspaceChanged(fallback)
      return
    }

    const current = selectable.find((w) => w.id === stored)
    if (!current) return

    const nextCaps = current.capabilities ?? []
    const { activeCapabilities } = useWorkspaceStore.getState()
    const capsChanged =
      nextCaps.length !== activeCapabilities.length ||
      nextCaps.some((cap, i) => cap !== activeCapabilities[i])

    if (capsChanged) {
      setActiveCapabilities(nextCaps)
    }
  }, [workspaces, activeId, onWorkspaceChanged, setActiveCapabilities])

  const activeWorkspace = useMemo(
    () => workspaces.find((w) => w.id === activeId) ?? null,
    [workspaces, activeId],
  )

  const handleSelect = async (workspace: Workspace) => {
    if (!workspace.is_active) {
      return
    }
    if (workspace.id === activeId) {
      setOpen(false)
      return
    }
    setOpen(false)
    await onWorkspaceChanged(workspace)
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

  const handleCopyId = (event: React.MouseEvent, workspaceId: string) => {
    event.preventDefault()
    event.stopPropagation()
    copyTextToClipboard(workspaceId, () => {
      setCopiedId(workspaceId)
      setTimeout(() => setCopiedId(null), 2000)
    })
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
            <div className="absolute left-0 right-0 mt-2 bg-white rounded-lg shadow-lg border border-gray-200 z-20 overflow-hidden">
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
                  const isInactive = !ws.is_active
                  const isCopied = copiedId === ws.id
                  return (
                    <div
                      key={ws.id}
                      className={`flex items-start gap-1 px-2 py-1 ${
                        isCurrent ? 'bg-primary-50/80' : ''
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => handleSelect(ws)}
                        disabled={isInactive}
                        className={`flex-1 min-w-0 px-2 py-1.5 text-left rounded-md transition-colors ${
                          isInactive
                            ? 'opacity-60 cursor-not-allowed'
                            : 'hover:bg-gray-50'
                        }`}
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="text-sm font-medium text-gray-900 truncate">
                              {ws.name}
                            </span>
                            {ws.is_default && (
                              <span className="text-[10px] font-medium uppercase tracking-wide text-gray-500 flex-shrink-0">
                                Default
                              </span>
                            )}
                            {isInactive && (
                              <span className="text-[10px] font-medium uppercase tracking-wide text-gray-500 flex-shrink-0">
                                Inactive
                              </span>
                            )}
                          </div>
                          <div className="mt-0.5 text-xs text-gray-500 truncate">
                            {ws.role_name ? `${ws.role_name} · ${ws.slug}` : ws.slug}
                          </div>
                        </div>
                      </button>
                      <div className="flex items-center gap-1 flex-shrink-0 pt-1.5 pr-1">
                        {!isInactive && (
                          <button
                            type="button"
                            onClick={(e) => handleCopyId(e, ws.id)}
                            className="p-1.5 rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
                            title="Copy workspace ID"
                            aria-label={`Copy workspace ID for ${ws.name}`}
                          >
                            {isCopied ? (
                              <Check className="h-3.5 w-3.5 text-green-600" />
                            ) : (
                              <Copy className="h-3.5 w-3.5" />
                            )}
                          </button>
                        )}
                        {isCurrent && !isInactive && (
                          <Check className="h-4 w-4 text-primary-600 mr-1" aria-hidden />
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>

              {activeWorkspace?.is_active && (
                <div className="px-4 py-2.5 border-t border-gray-100 bg-gray-50">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                      Active workspace ID
                    </span>
                    <button
                      type="button"
                      onClick={(e) => handleCopyId(e, activeWorkspace.id)}
                      className="text-[10px] font-medium text-primary-700 hover:text-primary-800"
                    >
                      {copiedId === activeWorkspace.id ? 'Copied' : 'Copy full ID'}
                    </button>
                  </div>
                  <code
                    className="block text-[11px] font-mono text-gray-600 truncate"
                    title={activeWorkspace.id}
                  >
                    {activeWorkspace.id}
                  </code>
                  <p className="mt-1 text-[10px] text-gray-500">
                    Use as <span className="font-mono">X-Workspace-Id</span> header
                  </p>
                </div>
              )}
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
