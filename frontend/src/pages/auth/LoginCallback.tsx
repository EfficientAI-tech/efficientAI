import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2, AlertCircle } from 'lucide-react'
import Logo from '../../components/Logo'
import { apiClient } from '../../lib/api'
import { useAuthStore } from '../../store/authStore'
import { exchangeAuthorizationCode, readPkceState } from '../../lib/oidc'

export default function LoginCallback() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { setSession } = useAuthStore()
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true

    async function completeLogin() {
      const code = searchParams.get('code')
      const state = searchParams.get('state')
      const oauthError = searchParams.get('error_description') || searchParams.get('error')

      if (oauthError) {
        setError(oauthError)
        return
      }
      if (!code) {
        setError('Missing authorization code from identity provider')
        return
      }

      const expectedState = readPkceState()
      if (expectedState && state && expectedState !== state) {
        setError('Invalid login state — try signing in again')
        return
      }

      try {
        const config = await apiClient.getAuthConfig()
        const provider = config.providers.find((p) => p.name === 'external_oidc' && p.enabled)
        if (!provider) {
          setError('SSO is not enabled on this server')
          return
        }

        const redirectUri = `${window.location.origin}/login/callback`
        const accessToken = await exchangeAuthorizationCode(provider, code, redirectUri)

        apiClient.setAccessToken(accessToken)
        const user = await apiClient.getMe()
        if (!active) return

        setSession(accessToken, user)

        const profile = await apiClient.getProfile()
        if (!active) return

        if ((profile.organizations?.length ?? 0) > 1) {
          navigate('/select-organization', { replace: true })
        } else {
          navigate('/', { replace: true })
        }
      } catch (err: any) {
        if (!active) return
        setError(err?.message || 'SSO sign-in failed')
      }
    }

    completeLogin()
    return () => {
      active = false
    }
  }, [navigate, searchParams, setSession])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-amber-50 via-yellow-50 to-orange-50 py-12 px-4">
      <div className="max-w-md w-full text-center space-y-6">
        <Logo textSize="xl" />
        {error ? (
          <div className="space-y-3">
            <AlertCircle className="w-8 h-8 mx-auto text-red-500" />
            <p className="text-sm text-gray-700">{error}</p>
            <button
              type="button"
              onClick={() => navigate('/login', { replace: true })}
              className="text-sm font-medium text-primary-700 hover:text-primary-800"
            >
              Back to sign in
            </button>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 text-gray-600">
            <Loader2 className="h-6 w-6 animate-spin" />
            <p className="text-sm">Completing sign-in...</p>
          </div>
        )}
      </div>
    </div>
  )
}
