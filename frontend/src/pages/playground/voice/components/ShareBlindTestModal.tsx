import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Copy,
  Loader2,
  Plus,
  Trash2,
  X,
  ExternalLink,
  Power,
  RefreshCw,
  Lock,
} from 'lucide-react'
import Button from '../../../../components/Button'
import { apiClient } from '../../../../lib/api'
import {
  BlindTestCustomMetric,
  BlindTestShareDetail,
} from '../types'

interface MetricDraft extends BlindTestCustomMetric {
  _localId: string
}

const DEFAULT_METRICS: MetricDraft[] = [
  { _localId: 'naturalness', key: 'naturalness', label: 'Naturalness', type: 'rating', scale: 5 },
  { _localId: 'clarity', key: 'clarity', label: 'Clarity', type: 'rating', scale: 5 },
  { _localId: 'comment', key: 'comment', label: 'Comment', type: 'comment' },
]

function makeLocalId(): string {
  return Math.random().toString(36).slice(2, 9)
}

function slugify(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9_\s]/g, '')
    .trim()
    .replace(/\s+/g, '_')
    .slice(0, 40)
}

interface ShareBlindTestModalProps {
  isOpen: boolean
  comparisonId: string
  defaultTitle: string
  onClose: () => void
}

export default function ShareBlindTestModal({
  isOpen,
  comparisonId,
  defaultTitle,
  onClose,
}: ShareBlindTestModalProps) {
  const queryClient = useQueryClient()

  const { data: existing, isLoading: existingLoading, refetch } = useQuery<BlindTestShareDetail | null>({
    queryKey: ['blind-test-share', comparisonId],
    queryFn: async () => {
      try {
        return await apiClient.getBlindTestShare(comparisonId)
      } catch (err: any) {
        if (err?.response?.status === 404) return null
        throw err
      }
    },
    enabled: isOpen,
  })

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [creatorNotes, setCreatorNotes] = useState('')
  const [metrics, setMetrics] = useState<MetricDraft[]>([])
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!isOpen) return
    if (existing) {
      setTitle(existing.title || defaultTitle || 'Voice Blind Test')
      setDescription(existing.description || '')
      setCreatorNotes(existing.creator_notes || '')
      setMetrics(
        (existing.custom_metrics || []).map(m => ({ ...m, _localId: makeLocalId() }))
      )
    } else if (!existingLoading) {
      setTitle(defaultTitle || 'Voice Blind Test')
      setDescription('Listen to each pair and tell us which voice you prefer.')
      setCreatorNotes('')
      setMetrics(DEFAULT_METRICS.map(m => ({ ...m, _localId: makeLocalId() })))
    }
  }, [existing, existingLoading, isOpen, defaultTitle])

  const publicUrl = useMemo(() => {
    if (!existing?.public_path) return ''
    return `${window.location.origin}${existing.public_path}`
  }, [existing?.public_path])

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        title: title.trim(),
        description: description.trim() || undefined,
        creator_notes: creatorNotes.trim() || undefined,
        custom_metrics: metrics.map(({ _localId, ...rest }) => ({
          ...rest,
          key: rest.key.trim() || slugify(rest.label),
          label: rest.label.trim(),
          ...(rest.type === 'rating' ? { scale: rest.scale ?? 5 } : {}),
        })),
      }
      return apiClient.createBlindTestShare(comparisonId, payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['blind-test-share', comparisonId] })
      queryClient.invalidateQueries({ queryKey: ['tts-comparison', comparisonId] })
      refetch()
    },
  })

  const toggleStatusMutation = useMutation({
    mutationFn: async (status: 'open' | 'closed') => {
      if (!existing) return null
      return apiClient.updateBlindTestShare(existing.id, { status })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['blind-test-share', comparisonId] })
      queryClient.invalidateQueries({ queryKey: ['tts-comparison', comparisonId] })
      refetch()
    },
  })

  const handleCopy = async () => {
    if (!publicUrl) return
    try {
      await navigator.clipboard.writeText(publicUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* ignore */
    }
  }

  const updateMetric = (id: string, patch: Partial<MetricDraft>) => {
    setMetrics(prev => prev.map(m => (m._localId === id ? { ...m, ...patch } : m)))
  }

  const addMetric = () => {
    setMetrics(prev => [
      ...prev,
      { _localId: makeLocalId(), key: '', label: '', type: 'rating', scale: 5 },
    ])
  }

  const removeMetric = (id: string) => {
    setMetrics(prev => prev.filter(m => m._localId !== id))
  }

  if (!isOpen) return null

  const saveError = saveMutation.error
    ? (saveMutation.error as any)?.response?.data?.detail || (saveMutation.error as any)?.message
    : null

  return createPortal(
    <div
      className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">
            {existing ? 'Manage Blind Test' : 'Create Blind Test'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="overflow-y-auto px-6 py-5 space-y-6">
          {existing && (
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-wide text-gray-500">Public link</p>
                  <p className="text-sm text-gray-700 font-mono break-all">
                    {publicUrl || existing.public_path}
                  </p>
                </div>
                <span
                  className={`px-2 py-0.5 text-xs rounded-full font-medium ${
                    existing.status === 'open'
                      ? 'bg-green-100 text-green-700'
                      : 'bg-red-100 text-red-700'
                  }`}
                >
                  {existing.status === 'open' ? 'Accepting responses' : 'Closed'}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  leftIcon={<Copy className="w-4 h-4" />}
                  onClick={handleCopy}
                >
                  {copied ? 'Copied!' : 'Copy link'}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  leftIcon={<ExternalLink className="w-4 h-4" />}
                  onClick={() => publicUrl && window.open(publicUrl, '_blank', 'noopener,noreferrer')}
                  disabled={!publicUrl}
                >
                  Open
                </Button>
                {existing.status === 'open' ? (
                  <Button
                    size="sm"
                    variant="danger"
                    leftIcon={<Power className="w-4 h-4" />}
                    onClick={() => toggleStatusMutation.mutate('closed')}
                    isLoading={toggleStatusMutation.isPending}
                  >
                    Close responses
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="success"
                    leftIcon={<RefreshCw className="w-4 h-4" />}
                    onClick={() => toggleStatusMutation.mutate('open')}
                    isLoading={toggleStatusMutation.isPending}
                  >
                    Reopen
                  </Button>
                )}
                {existing.response_count !== undefined && (
                  <span className="ml-auto text-xs text-gray-500">
                    {existing.response_count} response
                    {existing.response_count === 1 ? '' : 's'} so far
                  </span>
                )}
              </div>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Title</label>
            <input
              value={title}
              onChange={e => setTitle(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="e.g. Help us pick the best voice"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="Shown to raters above the form"
            />
          </div>

          <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-4">
            <div className="flex items-center gap-2 mb-1">
              <Lock className="w-4 h-4 text-amber-600" />
              <label className="block text-sm font-semibold text-amber-900">
                Internal notes (only visible to you)
              </label>
            </div>
            <p className="text-xs text-amber-800 mb-2">
              Track which voice / provider / source corresponds to each side. This is never
              shown to raters and never included in the public form, so the test stays blind.
            </p>
            <textarea
              value={creatorNotes}
              onChange={e => setCreatorNotes(e.target.value)}
              rows={4}
              className="w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
              placeholder={
                'e.g.\nA = Sarvam (Maitreyi, fast model)\nB = Original recording from call 0921\nGoal: pick the more natural Hindi voice'
              }
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-gray-700">
                Rating metrics & comment fields
              </label>
              <Button
                size="sm"
                variant="ghost"
                leftIcon={<Plus className="w-4 h-4" />}
                onClick={addMetric}
              >
                Add metric
              </Button>
            </div>
            <p className="text-xs text-gray-500 mb-3">
              Raters will rate <span className="font-medium">both Voice X and Voice Y</span> on each
              rating metric. Comment fields are per-sample notes.
            </p>
            <div className="space-y-2">
              {metrics.length === 0 && (
                <p className="text-sm text-gray-500 italic">
                  No extra metrics. Raters will only pick a preferred voice per sample.
                </p>
              )}
              {metrics.map(m => (
                <div
                  key={m._localId}
                  className="flex flex-wrap items-center gap-2 p-3 rounded-lg border border-gray-200 bg-white"
                >
                  <input
                    value={m.label}
                    onChange={e => {
                      const label = e.target.value
                      updateMetric(m._localId, {
                        label,
                        key: m.key.trim() ? m.key : slugify(label),
                      })
                    }}
                    placeholder="Label (e.g. Naturalness)"
                    className="flex-1 min-w-[160px] rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                  <select
                    value={m.type}
                    onChange={e =>
                      updateMetric(m._localId, {
                        type: e.target.value as 'rating' | 'comment',
                      })
                    }
                    className="rounded-md border border-gray-300 px-2 py-1.5 text-sm bg-white"
                  >
                    <option value="rating">Rating</option>
                    <option value="comment">Comment</option>
                  </select>
                  {m.type === 'rating' && (
                    <label className="flex items-center gap-1 text-sm text-gray-600">
                      Scale 1–
                      <input
                        type="number"
                        min={2}
                        max={10}
                        value={m.scale ?? 5}
                        onChange={e =>
                          updateMetric(m._localId, { scale: Math.max(2, Math.min(10, Number(e.target.value) || 5)) })
                        }
                        className="w-16 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                      />
                    </label>
                  )}
                  <button
                    onClick={() => removeMetric(m._localId)}
                    className="p-1.5 rounded text-red-500 hover:bg-red-50"
                    aria-label="Remove metric"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {saveError && (
            <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
              {String(saveError)}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-gray-200 bg-gray-50 rounded-b-xl">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => saveMutation.mutate()}
            disabled={!title.trim() || saveMutation.isPending}
            leftIcon={saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : undefined}
          >
            {existing ? 'Save changes' : 'Create share link'}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  )
}
