import { useCallback, useEffect, useState } from 'react'
import {
  AlertCircle,
  Check,
  Copy,
  KeyRound,
  Loader2,
  Plus,
  Trash2,
} from 'lucide-react'
import { Button, Chip, Switch } from '@heroui/react'
import { apiClient, type PlatformSignupCode } from '../../lib/api'

export default function PlatformSignupCodes() {
  const [codes, setCodes] = useState<PlatformSignupCode[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [gatedSignup, setGatedSignup] = useState<boolean | null>(null)

  const [showCreate, setShowCreate] = useState(false)
  const [newCode, setNewCode] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [newMaxUses, setNewMaxUses] = useState('')
  const [creating, setCreating] = useState(false)
  const [createdCodePlaintext, setCreatedCodePlaintext] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [updatingId, setUpdatingId] = useState<string | null>(null)

  const loadCodes = useCallback(async () => {
    setError('')
    setLoading(true)
    try {
      const [codeRows, authConfig] = await Promise.all([
        apiClient.listPlatformSignupCodes(),
        apiClient.getAuthConfig(),
      ])
      setCodes(codeRows)
      setGatedSignup(Boolean(authConfig.gated_signup))
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load signup codes')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadCodes()
  }, [loadCodes])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreating(true)
    setError('')
    try {
      const created = await apiClient.createPlatformSignupCode({
        code: newCode.trim(),
        label: newLabel.trim() || undefined,
        max_uses: newMaxUses ? parseInt(newMaxUses, 10) : undefined,
      })
      setCreatedCodePlaintext(created.code || newCode.trim())
      setNewCode('')
      setNewLabel('')
      setNewMaxUses('')
      setShowCreate(false)
      await loadCodes()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create code')
    } finally {
      setCreating(false)
    }
  }

  const handleToggleActive = async (row: PlatformSignupCode, active: boolean) => {
    setUpdatingId(row.id)
    setError('')
    try {
      await apiClient.updatePlatformSignupCode(row.id, { is_active: active })
      await loadCodes()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to update code')
    } finally {
      setUpdatingId(null)
    }
  }

  const handleDeactivate = async (row: PlatformSignupCode) => {
    if (!confirm(`Deactivate reference code "${row.label || row.id}"?`)) return
    setUpdatingId(row.id)
    setError('')
    try {
      await apiClient.deactivatePlatformSignupCode(row.id)
      await loadCodes()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to deactivate code')
    } finally {
      setUpdatingId(null)
    }
  }

  const copyCreatedCode = async () => {
    if (!createdCodePlaintext) return
    await navigator.clipboard.writeText(createdCodePlaintext)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium text-gray-900 flex items-center gap-2">
            <KeyRound className="h-5 w-5" />
            Signup reference codes
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            {gatedSignup === null
              ? 'Loading signup settings…'
              : gatedSignup
                ? 'Gated signup is enabled — new users must enter a valid code at registration.'
                : 'Gated signup is off — set auth.local_password.gated_signup.enabled: true in config.yml to require codes.'}
          </p>
        </div>
        <Button
          color="primary"
          startContent={<Plus className="h-4 w-4" />}
          className="bg-amber-100 text-amber-800 border border-amber-300"
          onPress={() => {
            setShowCreate(true)
            setCreatedCodePlaintext(null)
          }}
        >
          Create code
        </Button>
      </div>

      {createdCodePlaintext && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-amber-900">Code created — copy it now</p>
            <p className="font-mono text-lg text-amber-950 mt-1">{createdCodePlaintext}</p>
            <p className="text-xs text-amber-800 mt-1">
              This is the only time the plaintext code is shown.
            </p>
          </div>
          <Button
            variant="flat"
            startContent={copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            onPress={copyCreatedCode}
          >
            {copied ? 'Copied' : 'Copy code'}
          </Button>
        </div>
      )}

      {error && (
        <Chip color="danger" variant="flat" startContent={<AlertCircle className="w-4 h-4" />} className="w-full max-w-full h-auto py-2">
          {error}
        </Chip>
      )}

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : codes.length === 0 ? (
          <p className="text-center text-gray-500 py-12">No reference codes yet.</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                <th className="px-4 py-3 font-medium">Label</th>
                <th className="px-4 py-3 font-medium">Uses</th>
                <th className="px-4 py-3 font-medium">Expires</th>
                <th className="px-4 py-3 font-medium">Active</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {codes.map((row) => (
                <tr key={row.id} className="border-t border-gray-100">
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-900">{row.label || '—'}</div>
                    <div className="text-xs text-gray-400 font-mono">{row.id}</div>
                  </td>
                  <td className="px-4 py-3 text-gray-700">
                    {row.use_count}
                    {row.max_uses != null ? ` / ${row.max_uses}` : ' / ∞'}
                  </td>
                  <td className="px-4 py-3 text-gray-700">
                    {row.expires_at
                      ? new Date(row.expires_at).toLocaleString()
                      : 'Never'}
                  </td>
                  <td className="px-4 py-3">
                    <Switch
                      isSelected={row.is_active}
                      isDisabled={updatingId === row.id}
                      onValueChange={(v) => handleToggleActive(row, v)}
                      aria-label="Toggle code active"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <Button
                      size="sm"
                      variant="light"
                      color="danger"
                      startContent={<Trash2 className="h-4 w-4" />}
                      isDisabled={updatingId === row.id || !row.is_active}
                      onPress={() => handleDeactivate(row)}
                    >
                      Deactivate
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
          onClick={() => setShowCreate(false)}
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-md w-full p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Create reference code</h3>
            <form onSubmit={handleCreate} className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Code</label>
                <input
                  value={newCode}
                  onChange={(e) => setNewCode(e.target.value)}
                  required
                  minLength={4}
                  maxLength={64}
                  placeholder="e.g. BETA2026"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg uppercase focus:outline-none focus:border-amber-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Label (optional)</label>
                <input
                  value={newLabel}
                  onChange={(e) => setNewLabel(e.target.value)}
                  placeholder="Beta invite batch"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-amber-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Max uses (optional)
                </label>
                <input
                  type="number"
                  min={1}
                  value={newMaxUses}
                  onChange={(e) => setNewMaxUses(e.target.value)}
                  placeholder="Unlimited if empty"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-amber-500"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="light" onPress={() => setShowCreate(false)} isDisabled={creating}>
                  Cancel
                </Button>
                <Button type="submit" isLoading={creating} className="bg-amber-100 text-amber-800">
                  Create
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
