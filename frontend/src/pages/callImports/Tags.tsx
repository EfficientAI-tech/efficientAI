import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  Check,
  Edit3,
  Plus,
  Trash2,
  X,
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import type { CallImportTag } from '../../types/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'

const DEFAULT_NEW_TAG_COLOR = '#3b82f6'

export default function CallImportTagsPage() {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newColor, setNewColor] = useState(DEFAULT_NEW_TAG_COLOR)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editColor, setEditColor] = useState<string>('')

  const [pendingDelete, setPendingDelete] = useState<CallImportTag | null>(null)

  const { data: tags = [], isLoading } = useQuery({
    queryKey: ['call-import-tags'],
    queryFn: () => apiClient.listCallImportTags(),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      apiClient.createCallImportTag({
        name: newName.trim(),
        color: newColor || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import-tags'] })
      setCreating(false)
      setNewName('')
      setNewColor(DEFAULT_NEW_TAG_COLOR)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, name, color }: { id: string; name: string; color: string | null }) =>
      apiClient.updateCallImportTag(id, { name, color }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import-tags'] })
      setEditingId(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (tagId: string) => apiClient.deleteCallImportTag(tagId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import-tags'] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      setPendingDelete(null)
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Link
          to="/call-imports"
          className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Call Imports
        </Link>
        <Button
          variant="primary"
          size="sm"
          leftIcon={<Plus className="h-4 w-4" />}
          onClick={() => {
            setCreating(true)
            setNewName('')
            setNewColor(DEFAULT_NEW_TAG_COLOR)
          }}
        >
          New tag
        </Button>
      </div>

      <div>
        <h1 className="text-2xl font-bold text-gray-900">Call Import Tags</h1>
        <p className="mt-1 text-sm text-gray-600">
          Tags can be attached to call imports for fine-grained filtering on top
          of the dataset segregation.
        </p>
      </div>

      {creating && (
        <div className="bg-white shadow rounded-lg p-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 items-end">
            <div>
              <label
                htmlFor="new-tag-name"
                className="block text-xs font-medium text-gray-600 uppercase tracking-wide mb-1"
              >
                Name
              </label>
              <input
                id="new-tag-name"
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="e.g., high-priority"
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              />
            </div>
            <div>
              <label
                htmlFor="new-tag-color"
                className="block text-xs font-medium text-gray-600 uppercase tracking-wide mb-1"
              >
                Color
              </label>
              <input
                id="new-tag-color"
                type="color"
                value={newColor}
                onChange={(e) => setNewColor(e.target.value)}
                className="h-10 w-20 border border-gray-300 rounded-lg"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              variant="primary"
              size="sm"
              isLoading={createMutation.isPending}
              disabled={!newName.trim()}
              onClick={() => createMutation.mutate()}
              leftIcon={<Check className="h-4 w-4" />}
            >
              Create
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCreating(false)}
              disabled={createMutation.isPending}
            >
              Cancel
            </Button>
          </div>
          {createMutation.isError && (
            <div className="flex items-start gap-2 text-sm text-red-700">
              <AlertCircle className="h-4 w-4 mt-0.5" />
              <span>
                {(createMutation.error as any)?.response?.data?.detail ||
                  'Failed to create tag.'}
              </span>
            </div>
          )}
        </div>
      )}

      <div className="bg-white shadow rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-6 text-center text-gray-500">Loading tags...</div>
        ) : tags.length === 0 ? (
          <div className="p-12 text-center text-gray-500">
            <p>No tags yet.</p>
            <p className="text-xs mt-1">Use the "New tag" button to create one.</p>
          </div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Name
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Color
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {tags.map((tag) => {
                const isEditing = editingId === tag.id
                return (
                  <tr key={tag.id} className="hover:bg-gray-50">
                    <td className="px-6 py-3">
                      {isEditing ? (
                        <input
                          type="text"
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          className="w-full px-2 py-1 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-primary-500"
                        />
                      ) : (
                        <span
                          className="inline-flex items-center text-xs uppercase tracking-wide rounded-full px-2 py-0.5 border"
                          style={{
                            borderColor: tag.color || '#d1d5db',
                            color: tag.color || '#4b5563',
                          }}
                        >
                          {tag.name}
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-3">
                      {isEditing ? (
                        <input
                          type="color"
                          value={editColor || '#000000'}
                          onChange={(e) => setEditColor(e.target.value)}
                          className="h-8 w-16 border border-gray-300 rounded"
                        />
                      ) : tag.color ? (
                        <div className="flex items-center gap-2">
                          <span
                            className="inline-block h-4 w-4 rounded border border-gray-300"
                            style={{ backgroundColor: tag.color }}
                          />
                          <code className="text-xs text-gray-500">{tag.color}</code>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-400 italic">none</span>
                      )}
                    </td>
                    <td className="px-6 py-3 text-right">
                      {isEditing ? (
                        <div className="flex justify-end gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              updateMutation.mutate({
                                id: tag.id,
                                name: editName.trim(),
                                color: editColor || null,
                              })
                            }
                            disabled={!editName.trim() || updateMutation.isPending}
                            className="text-green-600 hover:text-green-700 disabled:opacity-40"
                            aria-label="Save"
                          >
                            <Check className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditingId(null)}
                            className="text-gray-400 hover:text-gray-600"
                            aria-label="Cancel"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        </div>
                      ) : (
                        <div className="flex justify-end gap-3">
                          <button
                            type="button"
                            onClick={() => {
                              setEditingId(tag.id)
                              setEditName(tag.name)
                              setEditColor(tag.color || '')
                            }}
                            className="text-gray-400 hover:text-primary-600"
                            aria-label={`Edit ${tag.name}`}
                          >
                            <Edit3 className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setPendingDelete(tag)}
                            className="text-gray-400 hover:text-red-600"
                            aria-label={`Delete ${tag.name}`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <ConfirmModal
        isOpen={pendingDelete !== null}
        title="Delete tag?"
        description={
          pendingDelete
            ? `“${pendingDelete.name}” will be removed from all imports it is attached to. This cannot be undone.`
            : ''
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={deleteMutation.isPending}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id)
        }}
        onCancel={() => {
          if (deleteMutation.isPending) return
          setPendingDelete(null)
        }}
      />
    </div>
  )
}
