import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, Eye, EyeOff } from 'lucide-react'
import { Button, Chip } from '@heroui/react'
import Logo from '../../components/Logo'
import { apiClient } from '../../lib/api'
import { usePlatformAdminStore } from '../../store/platformAdminStore'

export default function PlatformLogin() {
  const navigate = useNavigate()
  const { setSession } = usePlatformAdminStore()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)
    try {
      const res = await apiClient.platformLogin(email, password)
      setSession(res.access_token, res.admin)
      navigate('/platform')
    } catch (err: any) {
      const status = err?.response?.status
      const detail = err?.response?.data?.detail
      if (status === 404 && detail === 'Not found') {
        setError(
          'No platform admin exists in the database this API is connected to. ' +
            'Run migration 057, then: python -m scripts.create_platform_admin --email you@example.com',
        )
      } else if (status === 404) {
        setError(
          'Platform admin API was not found. Restart the backend with the latest code, ' +
            'then confirm POST /api/v1/platform/auth/login is reachable.',
        )
      } else if (!err?.response) {
        setError(
          `Could not reach the API at ${import.meta.env.VITE_API_URL || 'http://localhost:8000'}. ` +
            'Is the backend running?',
        )
      } else {
        setError(detail || 'Sign in failed')
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-b from-gray-50 to-white px-4">
      <div className="w-full max-w-md">
        <div className="flex justify-center mb-8">
          <Logo className="h-10" />
        </div>
        <div className="bg-white border border-gray-200 rounded-2xl shadow-sm p-8">
          <h1 className="text-xl font-semibold text-gray-900 text-center mb-1">Platform Admin</h1>
          <p className="text-sm text-gray-500 text-center mb-6">Sign in to manage organizations</p>
          <form onSubmit={handleSubmit} className="space-y-4">
            <input
              type="email"
              placeholder="admin@example.com"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full px-4 py-3 text-base text-gray-900 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white"
            />
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                placeholder="Password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full px-4 py-3 pr-12 text-base text-gray-900 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white"
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
              <Chip color="danger" variant="flat" startContent={<AlertCircle className="w-4 h-4" />} className="w-full max-w-full h-auto py-2">
                {error}
              </Chip>
            )}
            <Button
              type="submit"
              color="primary"
              isLoading={isLoading}
              className="w-full font-semibold bg-[#fef9c3] hover:bg-[#fef08a] text-[#a16207] border border-[#facc15]"
              size="lg"
              radius="full"
            >
              Sign in
            </Button>
          </form>
        </div>
      </div>
    </div>
  )
}
