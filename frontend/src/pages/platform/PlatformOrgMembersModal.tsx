import { useEffect, useState } from 'react'
import { AlertCircle, Eye, EyeOff, KeyRound, Loader2, Users, X } from 'lucide-react'
import { Button, Chip } from '@heroui/react'
import {
  apiClient,
  type PlatformOrganizationItem,
  type PlatformOrgUser,
} from '../../lib/api'
import { PASSWORD_POLICY_HINT, validatePasswordPolicy } from '../../lib/passwordPolicy'

type Props = {
  org: PlatformOrganizationItem
  onClose: () => void
}

function generateStrongPassword(): string {
  const buf = new Uint8Array(16)
  crypto.getRandomValues(buf)
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*'
  let pwd = ''
  for (let i = 0; i < buf.length; i++) {
    pwd += alphabet[buf[i] % alphabet.length]
  }
  return pwd
}

export default function PlatformOrgMembersModal({ org, onClose }: Props) {
  const [members, setMembers] = useState<PlatformOrgUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [resetTarget, setResetTarget] = useState<PlatformOrgUser | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [resetError, setResetError] = useState('')
  const [resetting, setResetting] = useState(false)
  const [resetSuccess, setResetSuccess] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiClient
      .listPlatformOrganizationUsers(org.id)
      .then((rows) => active && setMembers(rows))
      .catch((err: any) => {
        if (active) setError(err?.response?.data?.detail || 'Failed to load members')
      })
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [org.id])

  const openReset = (member: PlatformOrgUser) => {
    setResetTarget(member)
    setNewPassword('')
    setConfirmPassword('')
    setShowPassword(false)
    setResetError('')
    setResetSuccess('')
  }

  const closeReset = () => {
    setResetTarget(null)
    setNewPassword('')
    setConfirmPassword('')
    setResetError('')
  }

  const handleGeneratePassword = () => {
    const pwd = generateStrongPassword()
    setNewPassword(pwd)
    setConfirmPassword(pwd)
    setShowPassword(true)
    setResetError('')
  }

  const handleResetSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!resetTarget) return
    setResetError('')
    setResetSuccess('')

    const policy = validatePasswordPolicy(newPassword)
    if (!policy.valid) {
      setResetError(policy.message || 'Invalid password')
      return
    }
    if (newPassword !== confirmPassword) {
      setResetError('Passwords do not match')
      return
    }

    setResetting(true)
    try {
      await apiClient.platformResetUserPassword(org.id, resetTarget.id, newPassword)
      setResetSuccess(`Password reset for ${resetTarget.email}`)
      closeReset()
    } catch (err: any) {
      setResetError(err?.response?.data?.detail || 'Failed to reset password')
    } finally {
      setResetting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-xl max-w-3xl w-full max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <Users className="h-5 w-5" />
              {org.name}
            </h2>
            <p className="text-xs text-gray-500 font-mono mt-0.5">{org.id}</p>
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 overflow-y-auto flex-1 space-y-4">
          {error && (
            <Chip color="danger" variant="flat" startContent={<AlertCircle className="w-4 h-4" />}>
              {error}
            </Chip>
          )}
          {resetSuccess && (
            <Chip color="success" variant="flat">
              {resetSuccess}
            </Chip>
          )}

          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
            </div>
          ) : members.length === 0 ? (
            <p className="text-center text-gray-500 py-8">No members in this organization.</p>
          ) : (
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Email</th>
                  <th className="px-4 py-2 font-medium">Role</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {members.map((member) => (
                  <tr key={member.id} className="border-t border-gray-100">
                    <td className="px-4 py-3 text-gray-900">{member.email}</td>
                    <td className="px-4 py-3 capitalize text-gray-700">{member.role}</td>
                    <td className="px-4 py-3">
                      <Chip size="sm" color={member.is_active ? 'success' : 'default'} variant="flat">
                        {member.is_active ? 'Active' : 'Inactive'}
                      </Chip>
                    </td>
                    <td className="px-4 py-3">
                      <Button
                        size="sm"
                        variant="flat"
                        startContent={<KeyRound className="h-4 w-4" />}
                        onPress={() => openReset(member)}
                        isDisabled={!member.is_active}
                      >
                        Reset password
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {resetTarget && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4"
          onClick={closeReset}
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-md w-full p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-gray-900 mb-1">Reset password</h3>
            <p className="text-sm text-gray-600 mb-4">
              Set a new password for <span className="font-medium">{resetTarget.email}</span>. Share
              it securely — it is not emailed automatically.
            </p>
            <form onSubmit={handleResetSubmit} className="space-y-3">
              <div className="flex justify-between items-center">
                <label className="text-sm font-medium text-gray-700">New password</label>
                <button
                  type="button"
                  className="text-xs text-amber-700 hover:underline"
                  onClick={handleGeneratePassword}
                >
                  Generate strong password
                </button>
              </div>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={8}
                  maxLength={32}
                  placeholder={PASSWORD_POLICY_HINT}
                  className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-lg focus:outline-none focus:border-amber-500"
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 px-3 text-gray-400"
                  onClick={() => setShowPassword((v) => !v)}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <input
                type={showPassword ? 'text' : 'password'}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                placeholder="Confirm password"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-amber-500"
              />
              {resetError && (
                <Chip color="danger" variant="flat" className="w-full">
                  {resetError}
                </Chip>
              )}
              <div className="flex gap-2 justify-end pt-2">
                <Button variant="light" onPress={closeReset} isDisabled={resetting}>
                  Cancel
                </Button>
                <Button
                  type="submit"
                  color="primary"
                  isLoading={resetting}
                  className="bg-amber-100 text-amber-800 border border-amber-300"
                >
                  Reset password
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
