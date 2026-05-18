import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, FolderKanban, Loader2, Plus, X } from 'lucide-react'
import { apiClient } from '../lib/api'
import type { Workspace } from '../types/api'

const ACTIVE_WORKSPACE_KEY = 'activeWorkspaceId'

/**
 * Workspace switcher dropdown.
 *
 * Lives in the sidebar so the active workspace context is always visible.
 * Persists the selection in `localStorage` under `activeWorkspaceId`; the
 * shared axios client picks that up and forwards it as `X-Workspace-Id` on
 * every request, which is how the backend's `get_workspace_id` dependency
 * scopes listings.
 *
 * On any change (initial bootstrap into Default, or user-selected switch)
 * we blow away every react-query cache so views refetch against the new
 * workspace - no stale rows leaking between projects.
 */
export default function WorkspaceSwitcher() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newSlug, setNewSlug] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const {
    data: workspaces = [],
    isLoading,
    refetch,
  } = useQuery<Workspace[]>({
    queryKey: ['workspaces'],
    queryFn: () => apiClient.listWorkspaces(),
    staleTime: 60_000,
  })

  const [activeId, setActiveId] = useState<string | null>(() =>
    typeof window !== 'undefined'
      ? localStorage.getItem(ACTIVE_WORKSPACE_KEY)
      : null,
  )

  // Bootstrap: if we don't have a stored workspace, or the stored one
  // doesn't belong to this org (e.g. after an org switch), fall back to
  // the org's Default workspace. Migration 033 guarantees one exists.
  useEffect(() => {
    if (!workspaces.length) return
    const stored = localStorage.getItem(ACTIVE_WORKSPACE_KEY)
    const isValid = stored && workspaces.some((w) => w.id === stored)
    if (isValid) {
      if (stored !== activeId) setActiveId(stored)
      return
    }
    const fallback =
      workspaces.find((w) => w.is_default) ?? workspaces[0]
    if (!fallback) return
    localStorage.setItem(ACTIVE_WORKSPACE_KEY, fallback.id)
    setActiveId(fallback.id)
    // Refetch workspace-scoped views now that the header will start being
    // sent. Use a short delay so the localStorage write is visible to the
    // axios request interceptor by the time queries refire.
    queryClient.invalidateQueries()
  }, [workspaces, activeId, queryClient])

  const activeWorkspace = useMemo(
    () => workspaces.find((w) => w.id === activeId) ?? null,
    [workspaces, activeId],
  )

  const handleSelect = async (workspaceId: string) => {
    if (workspaceId === activeId) {
      setOpen(false)
      return
    }
    localStorage.setItem(ACTIVE_WORKSPACE_KEY, workspaceId)
    setActiveId(workspaceId)
    setOpen(false)
    // Invalidate all queries so the UI refetches against the new
    // workspace's data. Same pattern as OrgSwitcher.
    await queryClient.invalidateQueries()
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmedName = newName.trim()
    const trimmedSlug = newSlug.trim()
    if (!trimmedName) {
      setError('Name is required')
      return
    }
    setError('')
    setCreating(true)
    try {
      const created = await apiClient.createWorkspace({
        name: trimmedName,
        // Slug is optional - the backend derives it from the name
        // when omitted.
        ...(trimmedSlug ? { slug: trimmedSlug } : {}),
      })
      await refetch()
      setShowCreate(false)
      setNewName('')
      setNewSlug('')
      await handleSelect(created.id)
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || 'Could not create workspace',
      )
    } finally {
      setCreating(false)
    }
  }

  return (
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
            onClick={() => {
              setOpen(false)
              setShowCreate(false)
              setError('')
            }}
          />
          <div className="absolute left-0 right-0 mt-2 bg-white rounded-lg shadow-lg border border-gray-200 z-20">
            <div className="px-4 py-2 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center justify-between">
              <span>Workspaces</span>
              <button
                type="button"
                onClick={() => {
                  setShowCreate((v) => !v)
                  setError('')
                }}
                className="text-primary-600 hover:text-primary-700 normal-case font-medium flex items-center gap-1"
              >
                {showCreate ? (
                  <>
                    <X className="h-3 w-3" /> Cancel
                  </>
                ) : (
                  <>
                    <Plus className="h-3 w-3" /> New
                  </>
                )}
              </button>
            </div>

            {showCreate && (
              <form
                onSubmit={handleCreate}
                className="px-4 py-3 border-b border-gray-100 space-y-2 bg-gray-50"
              >
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Workspace name"
                  className="w-full px-2 py-1.5 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-primary-500"
                  autoFocus
                />
                <input
                  type="text"
                  value={newSlug}
                  onChange={(e) =>
                    setNewSlug(
                      e.target.value
                        .toLowerCase()
                        .replace(/[^a-z0-9-]/g, '-'),
                    )
                  }
                  placeholder="slug (optional)"
                  className="w-full px-2 py-1.5 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
                {error && (
                  <div className="text-xs text-red-600">{error}</div>
                )}
                <button
                  type="submit"
                  disabled={creating}
                  className="w-full px-2 py-1.5 text-sm font-medium text-white bg-primary-600 rounded hover:bg-primary-700 disabled:opacity-60 flex items-center justify-center gap-2"
                >
                  {creating && (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  )}
                  Create workspace
                </button>
              </form>
            )}

            <div className="max-h-80 overflow-y-auto py-1">
              {workspaces.length === 0 && !isLoading && (
                <div className="px-4 py-3 text-sm text-gray-500">
                  No workspaces yet.
                </div>
              )}
              {workspaces.map((ws) => {
                const isCurrent = ws.id === activeId
                return (
                  <button
                    key={ws.id}
                    type="button"
                    onClick={() => handleSelect(ws.id)}
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
                        {ws.slug}
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
  )
}
