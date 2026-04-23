import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'
import { apiClient } from '../../lib/api'
import type { AuthConfigResponse, AuthProviderConfig } from '../../lib/api'
import { AlertCircle, ArrowLeft } from 'lucide-react'
import Logo from '../../components/Logo'
import { Card, CardBody, Button, Divider, Chip, Tabs, Tab } from '@heroui/react'

/**
 * Provider-aware sign-in screen.
 *
 * The backend at /api/v1/auth/config tells us which login methods are enabled:
 * API key, local password, Keycloak SSO, external OIDC. We render a tab for
 * each one and pick a sensible default (password > SSO > API key).
 */

type Mode = 'password' | 'signup' | 'apikey' | 'sso'

export default function Login() {
  const navigate = useNavigate()
  const { setApiKey, setSession } = useAuthStore()

  const [authConfig, setAuthConfig] = useState<AuthConfigResponse | null>(null)
  const [loadingConfig, setLoadingConfig] = useState(true)

  const [mode, setMode] = useState<Mode>('password')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [orgName, setOrgName] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [apiKey, setApiKeyValue] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    let active = true
    apiClient
      .getAuthConfig()
      .then((cfg) => {
        if (!active) return
        setAuthConfig(cfg)
        // Pick a sensible default tab based on what's enabled server-side.
        const byName = (n: string) => cfg.providers.find((p) => p.name === n && p.enabled)
        if (byName('local_password')) setMode('password')
        else if (byName('keycloak') || byName('external_oidc')) setMode('sso')
        else if (byName('api_key')) setMode('apikey')
      })
      .catch(() => {
        if (!active) return
        // If the config endpoint is unreachable (old backend, network issue),
        // fall back to the API-key-only UX so OSS users aren't locked out.
        setAuthConfig({
          providers: [
            {
              name: 'api_key',
              enabled: true,
              display_name: 'API Key',
              description: 'Sign in with an EfficientAI API key.',
            },
          ],
          tier: 'oss',
        })
        setMode('apikey')
      })
      .finally(() => active && setLoadingConfig(false))
    return () => {
      active = false
    }
  }, [])

  const providerByName = (n: AuthProviderConfig['name']) =>
    authConfig?.providers.find((p) => p.name === n && p.enabled)
  const localPwd = providerByName('local_password')
  const keycloak = providerByName('keycloak')
  const oidc = providerByName('external_oidc')
  const apikeyProv = providerByName('api_key')

  const handlePasswordLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)
    try {
      const res = await apiClient.loginWithPassword(email, password)
      setSession(res.access_token, res.user)
      navigate('/')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Invalid email or password')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)
    try {
      const res = await apiClient.signup({
        email,
        password,
        organization_name: orgName || undefined,
        first_name: firstName || undefined,
        last_name: lastName || undefined,
      })
      setSession(res.access_token, res.user)
      navigate('/')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Sign up failed')
    } finally {
      setIsLoading(false)
    }
  }

  const handleApiKeyLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)
    try {
      apiClient.setApiKey(apiKey)
      const res = await apiClient.validateApiKey()
      if (res.valid) {
        setApiKey(apiKey)
        navigate('/')
      } else {
        setError('Invalid API key')
      }
    } catch (err: any) {
      apiClient.clearApiKey()
      setError(err?.response?.data?.detail || 'Failed to validate API key')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSsoRedirect = (provider: AuthProviderConfig) => {
    // For Keycloak we have a full authorize URL. We kick off the standard
    // OIDC authorization-code flow with the SPA as the redirect target.
    // The callback page exchanges the code for tokens (not included here -
    // enterprise deployments typically fork this for custom UX).
    const authorizeUrl = provider.oidc_authorize_url
    if (!authorizeUrl || !provider.oidc_client_id) {
      setError(
        `${provider.display_name} is enabled but not fully configured. Ask your admin to set the base URL, realm, and client_id.`
      )
      return
    }
    const redirect = `${window.location.origin}/login/callback`
    const params = new URLSearchParams({
      client_id: provider.oidc_client_id,
      redirect_uri: redirect,
      response_type: 'code',
      scope: 'openid profile email',
      state: crypto.randomUUID(),
    })
    window.location.href = `${authorizeUrl}?${params.toString()}`
  }

  if (loadingConfig) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-700" />
      </div>
    )
  }

  const tabs: Array<{ key: Mode; label: string; show: boolean }> = [
    { key: 'password', label: 'Sign in', show: !!localPwd },
    { key: 'signup', label: 'Create account', show: !!localPwd?.supports_signup },
    { key: 'sso', label: 'SSO', show: !!(keycloak || oidc) },
    { key: 'apikey', label: 'API key', show: !!apikeyProv },
  ].filter((t) => t.show)

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-amber-50 via-yellow-50 to-orange-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-primary-200 rounded-full mix-blend-multiply filter blur-xl opacity-30 animate-pulse" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-orange-200 rounded-full mix-blend-multiply filter blur-xl opacity-30 animate-pulse" />
      </div>

      <div className="max-w-md w-full space-y-8 relative z-10">
        <div className="text-center">
          <div className="flex justify-center mb-4">
            <Logo textSize="xl" />
          </div>
          <p className="mt-2 text-sm text-gray-600">
            {authConfig?.tier === 'enterprise' ? 'Enterprise' : 'Self-Hosted'} · Sign in to continue
          </p>
        </div>

        <Card className="shadow-xl">
          <CardBody className="p-6">
            {tabs.length > 1 && (
              <Tabs
                aria-label="Sign in methods"
                selectedKey={mode}
                onSelectionChange={(k) => {
                  setMode(k as Mode)
                  setError('')
                }}
                className="mb-4"
              >
                {tabs.map((t) => (
                  <Tab key={t.key} title={t.label} />
                ))}
              </Tabs>
            )}

            {mode === 'password' && localPwd && (
              <form onSubmit={handlePasswordLogin} className="space-y-4">
                <input
                  type="email"
                  placeholder="you@example.com"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="w-full px-4 py-3 text-base text-gray-900 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white"
                />
                <input
                  type="password"
                  placeholder="Password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="w-full px-4 py-3 text-base text-gray-900 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white"
                />
                {error && (
                  <Chip color="danger" variant="flat" startContent={<AlertCircle className="w-4 h-4" />} className="w-full max-w-full h-auto py-2">
                    {error}
                  </Chip>
                )}
                <Button type="submit" color="primary" isLoading={isLoading} className="w-full font-semibold bg-[#fef9c3] hover:bg-[#fef08a] text-[#a16207] border border-[#facc15]" size="lg" radius="full">
                  Sign in
                </Button>
              </form>
            )}

            {mode === 'signup' && localPwd?.supports_signup && (
              <form onSubmit={handleSignup} className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <input type="text" placeholder="First name" value={firstName} onChange={(e) => setFirstName(e.target.value)} className="px-4 py-3 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white" />
                  <input type="text" placeholder="Last name" value={lastName} onChange={(e) => setLastName(e.target.value)} className="px-4 py-3 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white" />
                </div>
                <input type="email" placeholder="you@example.com" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="w-full px-4 py-3 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white" />
                <input type="password" placeholder="Password (min 8 chars)" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} className="w-full px-4 py-3 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white" />
                <input type="text" placeholder="Organization name (optional)" value={orgName} onChange={(e) => setOrgName(e.target.value)} className="w-full px-4 py-3 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white" />
                {error && (
                  <Chip color="danger" variant="flat" startContent={<AlertCircle className="w-4 h-4" />} className="w-full max-w-full h-auto py-2">
                    {error}
                  </Chip>
                )}
                <Button type="submit" color="primary" isLoading={isLoading} className="w-full font-semibold bg-[#fef9c3] hover:bg-[#fef08a] text-[#a16207]" size="lg" radius="full">
                  Create account
                </Button>
                <p className="text-xs text-gray-500 text-center">
                  By signing up you become the admin of a new organization. You can invite teammates later.
                </p>
              </form>
            )}

            {mode === 'sso' && (keycloak || oidc) && (
              <div className="space-y-3">
                {keycloak && (
                  <Button onPress={() => handleSsoRedirect(keycloak)} className="w-full font-semibold" size="lg" radius="full" color="primary" variant="bordered">
                    Continue with {keycloak.display_name}
                  </Button>
                )}
                {oidc && (
                  <Button onPress={() => handleSsoRedirect(oidc)} className="w-full font-semibold" size="lg" radius="full" color="primary" variant="bordered">
                    Continue with {oidc.display_name}
                  </Button>
                )}
                {error && (
                  <Chip color="danger" variant="flat" startContent={<AlertCircle className="w-4 h-4" />} className="w-full max-w-full h-auto py-2">
                    {error}
                  </Chip>
                )}
                <p className="text-xs text-gray-500 text-center">
                  You'll be redirected to your identity provider to complete sign-in.
                </p>
              </div>
            )}

            {mode === 'apikey' && apikeyProv && (
              <form onSubmit={handleApiKeyLogin} className="space-y-4">
                <input type="text" placeholder="Enter your API key" value={apiKey} onChange={(e) => setApiKeyValue(e.target.value)} required className="w-full px-4 py-3 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white" />
                {error && (
                  <Chip color="danger" variant="flat" startContent={<AlertCircle className="w-4 h-4" />} className="w-full max-w-full h-auto py-2">
                    {error}
                  </Chip>
                )}
                <Button type="submit" color="primary" isLoading={isLoading} className="w-full font-semibold bg-[#fef9c3] hover:bg-[#fef08a] text-[#a16207]" size="lg" radius="full">
                  Sign in with API key
                </Button>
                <p className="text-xs text-gray-500 text-center">
                  New keys are created from Settings &rarr; API Keys after you sign in.
                </p>
              </form>
            )}

            {tabs.length === 0 && (
              <div className="space-y-3 text-center">
                <AlertCircle className="w-8 h-8 mx-auto text-red-500" />
                <p className="text-sm text-gray-700">
                  No authentication providers are enabled on this deployment. Ask your administrator to set{' '}
                  <code className="px-1 bg-gray-100 rounded">auth.providers</code> in <code className="px-1 bg-gray-100 rounded">config.yml</code>.
                </p>
              </div>
            )}
          </CardBody>
        </Card>

        {authConfig && authConfig.providers.length > 1 && (
          <div className="text-center text-xs text-gray-500">
            <Divider className="my-3" />
            <p>
              Enabled providers:{' '}
              {authConfig.providers.filter((p) => p.enabled).map((p) => p.display_name).join(' · ')}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
