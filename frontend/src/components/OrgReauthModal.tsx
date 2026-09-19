import { useEffect, useState } from 'react'
import { Building2, Eye, EyeOff, Loader2, X } from 'lucide-react'
import Button from './Button'

type OrgReauthModalProps = {
  open: boolean
  organizationName: string
  email?: string | null
  isLoading?: boolean
  error?: string
  onClose: () => void
  onSubmit: (password: string) => Promise<unknown>
}

export default function OrgReauthModal({
  open,
  organizationName,
  email,
  isLoading = false,
  error = '',
  onClose,
  onSubmit,
}: OrgReauthModalProps) {
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  useEffect(() => {
    if (!open) {
      setPassword('')
      setShowPassword(false)
    }
  }, [open])

  if (!open) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    await onSubmit(password)
  }

  const handleClose = () => {
    if (isLoading) return
    setPassword('')
    setShowPassword(false)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-[60] overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className="fixed inset-0 bg-gray-500/75 transition-opacity" onClick={handleClose} />
        <div className="relative bg-white rounded-2xl shadow-xl max-w-md w-full p-6">
          <button
            type="button"
            onClick={handleClose}
            disabled={isLoading}
            className="absolute right-4 top-4 text-gray-400 hover:text-gray-600 disabled:opacity-50"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>

          <div className="flex items-center gap-3 mb-2">
            <div className="p-2.5 rounded-full bg-[#fef9c3]">
              <Building2 className="w-5 h-5 text-[#ca8a04]" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900 pr-8">Sign in to switch</h3>
          </div>

          <p className="text-sm text-gray-600 mb-5">
            Enter the password for <span className="font-medium text-gray-900">{organizationName}</span>
            {email ? (
              <>
                {' '}
                as <span className="font-medium text-gray-900">{email}</span>
              </>
            ) : null}
            .
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                placeholder="Organization password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isLoading}
                className="w-full px-4 py-3 pr-12 text-base text-gray-900 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white disabled:opacity-60"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute inset-y-0 right-0 px-4 flex items-center text-gray-400 hover:text-gray-600"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
              </button>
            </div>

            {error && (
              <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <div className="flex justify-end gap-3 pt-1">
              <Button type="button" variant="ghost" onClick={handleClose} disabled={isLoading}>
                Cancel
              </Button>
              <button
                type="submit"
                disabled={isLoading || !password}
                className="px-4 py-2 rounded-full font-semibold transition-colors disabled:opacity-50 bg-[#fef9c3] hover:bg-[#fef08a] text-[#a16207] border border-[#facc15]"
              >
                {isLoading ? (
                  <span className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Signing in
                  </span>
                ) : (
                  'Continue'
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
