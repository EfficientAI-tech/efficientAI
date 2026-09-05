import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Edit2, Loader2, Trash2, Volume2 } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { useToast } from '../../hooks/useToast'
import Button from '../../components/Button'
import AmbientPreviewControls from './AmbientPreviewControls'
import { useAmbientPreview } from './useAmbientPreview'

export default function AmbientNoiseLibraryPanel() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: string; name: string } | null>(null)
  const [editingAssetId, setEditingAssetId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const preview = useAmbientPreview()

  const { data: assets = [], isLoading: listLoading } = useQuery({
    queryKey: ['ambient-library'],
    queryFn: () => apiClient.listAmbientLibrary(),
  })

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      apiClient.updateAmbientLibraryAsset(id, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ambient-library'] })
      setEditingAssetId(null)
      setEditingName('')
      showToast('Name updated', 'success')
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || err?.message || 'Rename failed', 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (assetId: string) => apiClient.deleteAmbientLibraryAsset(assetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ambient-library'] })
      setDeleteConfirm(null)
      preview.stop()
      showToast('Background noise deleted', 'success')
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || err?.message || 'Delete failed', 'error')
    },
  })

  const startEditing = (asset: { id: string; name: string }) => {
    setEditingAssetId(asset.id)
    setEditingName(asset.name)
  }

  const cancelEditing = () => {
    setEditingAssetId(null)
    setEditingName('')
  }

  const saveEditing = (assetId: string) => {
    const trimmed = editingName.trim()
    if (!trimmed) {
      showToast('Name cannot be empty', 'error')
      return
    }
    renameMutation.mutate({ id: assetId, name: trimmed })
  }

  return (
    <div className="space-y-4">
      {preview.error ? (
        <p className="text-xs text-red-600 flex items-center gap-1.5">
          <Volume2 className="h-3.5 w-3.5 shrink-0" />
          {preview.error}
        </p>
      ) : null}

      {listLoading ? (
        <div className="flex items-center justify-center py-12 text-sm text-gray-500">
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          Loading library…
        </div>
      ) : assets.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center">
          <Volume2 className="w-9 h-9 text-gray-400 mx-auto mb-3" />
          <h3 className="text-sm font-medium text-gray-900 mb-1">No background noise yet</h3>
          <p className="text-xs text-gray-500 max-w-sm mx-auto">
            Use <span className="font-medium">Upload Audio</span> above to add ambient loops.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {assets.map((asset) => {
            const previewId = `library:${asset.id}`
            const isEditing = editingAssetId === asset.id
            const active = preview.isActive(previewId)

            return (
              <div
                key={asset.id}
                className="bg-white rounded-lg border border-gray-200 shadow-sm hover:border-gray-300 transition-colors"
              >
                <div className="p-3 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      {isEditing ? (
                        <div className="space-y-1.5">
                          <input
                            type="text"
                            value={editingName}
                            onChange={(e) => setEditingName(e.target.value)}
                            className="w-full rounded-md border border-gray-300 px-2 py-1 text-xs focus:border-primary-500 focus:ring-primary-500"
                            autoFocus
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') saveEditing(asset.id)
                              if (e.key === 'Escape') cancelEditing()
                            }}
                          />
                          <div className="flex gap-1.5">
                            <Button
                              type="button"
                              size="sm"
                              variant="primary"
                              isLoading={renameMutation.isPending}
                              leftIcon={<Check className="h-3 w-3" />}
                              onClick={() => saveEditing(asset.id)}
                            >
                              Save
                            </Button>
                            <Button type="button" size="sm" variant="outline" onClick={cancelEditing}>
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="flex items-center gap-1 min-w-0">
                            <h3 className="text-xs font-semibold text-gray-900 truncate">{asset.name}</h3>
                            <button
                              type="button"
                              onClick={() => startEditing(asset)}
                              className="p-0.5 text-gray-400 hover:text-primary-600 rounded shrink-0"
                              title="Rename"
                            >
                              <Edit2 className="h-3 w-3" />
                            </button>
                          </div>
                          <p className="text-[10px] text-gray-400 truncate" title={asset.original_filename || undefined}>
                            {asset.original_filename || 'Custom upload'}
                            {asset.created_at ? ` · ${new Date(asset.created_at).toLocaleDateString()}` : ''}
                          </p>
                        </>
                      )}
                    </div>
                    {!isEditing ? (
                      <button
                        type="button"
                        onClick={() => setDeleteConfirm({ id: asset.id, name: asset.name })}
                        className="p-1 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded shrink-0"
                        title="Delete"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </div>

                  <AmbientPreviewControls
                    compact
                    previewId={previewId}
                    onToggle={() =>
                      preview.togglePreview(previewId, async () => {
                        const { url } = await apiClient.getAmbientLibraryPreviewUrl(asset.id)
                        return url
                      })
                    }
                    currentTime={active ? preview.currentTime : 0}
                    duration={active ? preview.duration : 0}
                    onSeek={preview.seek}
                    volume={preview.volume}
                    onVolumeChange={preview.setVolume}
                    isPlaying={preview.isPlaying(previewId)}
                    isLoading={preview.isLoading(previewId)}
                    isActive={active}
                  />
                </div>
              </div>
            )
          })}
        </div>
      )}

      {deleteConfirm ? (
        <div className="fixed inset-0 bg-gray-500/75 flex items-center justify-center z-[9999] p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Delete background noise?</h3>
            <p className="text-sm text-gray-600 mb-6">
              Remove <span className="font-medium">{deleteConfirm.name}</span> from the library? Personas still using
              it must be reassigned first.
            </p>
            <div className="flex gap-3">
              <Button variant="outline" className="flex-1" onClick={() => setDeleteConfirm(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                className="flex-1"
                isLoading={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate(deleteConfirm.id)}
              >
                Delete
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
