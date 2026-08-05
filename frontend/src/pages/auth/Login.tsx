import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'
import { apiClient, isLoginOrgSelectionResponse } from '../../lib/api'
import type { AuthConfigResponse, AuthProviderConfig, LoginOrgOption } from '../../lib/api'
import { buildAuthorizeUrl } from '../../lib/oidc'
import { PASSWORD_POLICY_HINT, validatePasswordPolicy } from '../../lib/passwordPolicy'
import { AlertCircle, Building2, Eye, EyeOff, Loader2 } from 'lucide-react'
import Logo from '../../components/Logo'
import { Card, CardBody, Button, Divider, Chip, Tabs, Tab } from '@heroui/react'

/**
 * Provider-aware sign-in screen.
 *
 * The backend at /api/v1/auth/config tells us which interactive login methods
 * are enabled: local password (email + password) and enterprise OIDC SSO
 * (Okta, Azure AD, Google Workspace, AWS Cognito, Auth0, ...). API keys are
 * still a fully supported auth method for scripts / SDKs / CI, but they are
 * intentionally not exposed as a login option on the UI - interactive users
 * sign in with an email/password or via SSO and mint API keys from Settings
 * afterwards.
 */

type Mode = 'password' | 'signup' | 'sso'
type LoginStep = 'credentials' | 'org-select'

export default function Login() {
  const navigate = useNavigate()
  const { setSession } = useAuthStore()

  const [authConfig, setAuthConfig] = useState<AuthConfigResponse | null>(null)
  const [loadingConfig, setLoadingConfig] = useState(true)
  const [configError, setConfigError] = useState(false)

  const [mode, setMode] = useState<Mode>('password')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [orgName, setOrgName] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [loginStep, setLoginStep] = useState<LoginStep>('credentials')
  const [orgOptions, setOrgOptions] = useState<LoginOrgOption[]>([])
  const [selectingOrgId, setSelectingOrgId] = useState<string | null>(null)
  const [showPassword, setShowPassword] = useState(false)

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
        else if (byName('external_oidc')) setMode('sso')
      })
      .catch(() => {
        if (!active) return
        // Config endpoint unreachable - we can't know which providers are on,
        // so surface a clear error instead of guessing. The user's best next
        // step is to check that the backend is running.
        setConfigError(true)
      })
      .finally(() => active && setLoadingConfig(false))
    return () => {
      active = false
    }
  }, [])

  const providerByName = (n: AuthProviderConfig['name']) =>
    authConfig?.providers.find((p) => p.name === n && p.enabled)
  const localPwd = providerByName('local_password')
  const oidc = providerByName('external_oidc')

  const handlePasswordLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)
    try {
      const res = await apiClient.loginWithPassword(email, password)
      if (isLoginOrgSelectionResponse(res)) {
        setOrgOptions(res.organizations)
        setLoginStep('org-select')
        return
      }
      setSession(res.access_token, res.user, res.refresh_token)
      navigate('/')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Invalid email or password')
    } finally {
      setIsLoading(false)
    }
  }

  const handleOrgSelect = async (organizationId: string) => {
    setError('')
    setSelectingOrgId(organizationId)
    try {
      const res = await apiClient.loginWithPassword(email, password, organizationId)
      if (isLoginOrgSelectionResponse(res)) {
        setError('Organization selection failed — try again')
        return
      }
      setSession(res.access_token, res.user, res.refresh_token)
      navigate('/')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not sign in to the selected organization')
    } finally {
      setSelectingOrgId(null)
    }
  }

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const policy = validatePasswordPolicy(password)
    if (!policy.valid) {
      setError(policy.message || 'Invalid password')
      return
    }
    setIsLoading(true)
    try {
      const res = await apiClient.signup({
        email,
        password,
        organization_name: orgName || undefined,
        first_name: firstName || undefined,
        last_name: lastName || undefined,
      })
      setSession(res.access_token, res.user, res.refresh_token)
      navigate('/')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Sign up failed')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSsoRedirect = async (provider: AuthProviderConfig) => {
    if (!provider.oidc_client_id) {
      setError(
        `${provider.display_name} is enabled but not fully configured. Ask your admin to set the issuer and client_id.`
      )
      return
    }

    try {
      const redirect = `${window.location.origin}/login/callback`
      const authorizeUrl = await buildAuthorizeUrl(provider, redirect)
      window.location.href = authorizeUrl
    } catch (err: any) {
      setError(
        err?.message ||
          `Could not start sign-in with ${provider.display_name}. Verify the issuer URL is reachable from your browser.`
      )
    }
  }

  if (loadingConfig) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-700" />
      </div>
    )
  }

  const tabs: Array<{ key: Mode; label: string; show: boolean }> = (
    [
      { key: 'password', label: 'Sign in', show: !!localPwd },
      { key: 'signup', label: 'Create account', show: !!localPwd?.supports_signup },
      { key: 'sso', label: 'SSO', show: !!oidc },
    ] satisfies Array<{ key: Mode; label: string; show: boolean }>
  ).filter((t) => t.show)

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
                  setShowPassword(false)
                }}
                variant="solid"
                radius="full"
                fullWidth
                classNames={{
                  base: 'mb-4',
                  tabList: 'w-full bg-gray-100 p-1 rounded-full',
                  tab: 'flex-1 h-10 px-3 data-[hover=true]:opacity-100',
                  cursor:
                    'bg-[#fef08a] border border-[#facc15] shadow-sm rounded-full',
                  tabContent:
                    'text-sm font-medium text-gray-500 group-data-[selected=true]:text-[#854d0e]',
                }}
              >
                {tabs.map((t) => (
                  <Tab key={t.key} title={t.label} />
                ))}
              </Tabs>
            )}

            {mode === 'password' && localPwd && loginStep === 'credentials' && (
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
                    title={showPassword ? 'Hide password' : 'Show password'}
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
                <Button type="submit" color="primary" isLoading={isLoading} className="w-full font-semibold bg-[#fef9c3] hover:bg-[#fef08a] text-[#a16207] border border-[#facc15]" size="lg" radius="full">
                  Sign in
                </Button>
              </form>
            )}

            {mode === 'password' && localPwd && loginStep === 'org-select' && (
              <div className="space-y-4">
                <p className="text-sm text-gray-600 text-center">
                  Your account belongs to multiple organizations. Choose one to continue.
                </p>
                <div className="space-y-2">
                  {orgOptions.map((org) => {
                    const isSelecting = selectingOrgId === org.id
                    return (
                      <button
                        key={org.id}
                        type="button"
                        disabled={!!selectingOrgId}
                        onClick={() => handleOrgSelect(org.id)}
                        className="w-full px-4 py-3 text-left border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors flex items-center gap-3 disabled:opacity-60"
                      >
                        <Building2 className="h-5 w-5 text-gray-500 flex-shrink-0" />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-gray-900 truncate">{org.name}</div>
                          <div className="text-xs text-gray-500 capitalize">{org.role}</div>
                        </div>
                        {isSelecting && (
                          <Loader2 className="h-4 w-4 text-gray-400 animate-spin flex-shrink-0" />
                        )}
                      </button>
                    )
                  })}
                </div>
                {error && (
                  <Chip color="danger" variant="flat" startContent={<AlertCircle className="w-4 h-4" />} className="w-full max-w-full h-auto py-2">
                    {error}
                  </Chip>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setLoginStep('credentials')
                    setOrgOptions([])
                    setError('')
                  }}
                  className="w-full text-sm text-gray-600 hover:text-gray-800"
                >
                  Back to sign in
                </button>
              </div>
            )}

            {mode === 'signup' && localPwd?.supports_signup && (
              <form onSubmit={handleSignup} className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <input type="text" placeholder="First name" value={firstName} onChange={(e) => setFirstName(e.target.value)} className="px-4 py-3 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white" />
                  <input type="text" placeholder="Last name" value={lastName} onChange={(e) => setLastName(e.target.value)} className="px-4 py-3 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white" />
                </div>
                <input type="email" placeholder="you@example.com" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="w-full px-4 py-3 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white" />
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    placeholder={`Password (${PASSWORD_POLICY_HINT})`}
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={8}
                    maxLength={32}
                    className="w-full px-4 py-3 pr-12 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute inset-y-0 right-0 px-4 flex items-center text-gray-400 hover:text-gray-600"
                    title={showPassword ? 'Hide password' : 'Show password'}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                  </button>
                </div>
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

            {mode === 'sso' && oidc && (
              <div className="space-y-3">
                <Button onPress={() => handleSsoRedirect(oidc)} className="w-full font-semibold" size="lg" radius="full" color="primary" variant="bordered">
                  Continue with {oidc.display_name}
                </Button>
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

            {configError && (
              <div className="space-y-3 text-center">
                <AlertCircle className="w-8 h-8 mx-auto text-red-500" />
                <p className="text-sm text-gray-700">
                  Could not reach the authentication service. Make sure the
                  backend is running and try again.
                </p>
              </div>
            )}

            {!configError && tabs.length === 0 && (
              <div className="space-y-3 text-center">
                <AlertCircle className="w-8 h-8 mx-auto text-red-500" />
                <p className="text-sm text-gray-700">
                  No interactive sign-in methods are enabled. Ask your
                  administrator to add{' '}
                  <code className="px-1 bg-gray-100 rounded">local_password</code>{' '}
                  or <code className="px-1 bg-gray-100 rounded">external_oidc</code>{' '}
                  to <code className="px-1 bg-gray-100 rounded">auth.providers</code>{' '}
                  in <code className="px-1 bg-gray-100 rounded">config.yml</code>.
                </p>
                <p className="text-xs text-gray-500">
                  API keys remain available for programmatic access — mint one
                  with <code className="px-1 bg-gray-100 rounded">scripts/create_api_key.py</code>.
                </p>
              </div>
            )}
          </CardBody>
        </Card>

        {authConfig && (() => {
          // Only list interactive providers here - API keys are a programmatic
          // auth method and aren't a sign-in option on this screen.
          const interactive = authConfig.providers.filter(
            (p) => p.enabled && p.name !== 'api_key'
          )
          if (interactive.length <= 1) return null
          return (
            <div className="text-center text-xs text-gray-500">
              <Divider className="my-3" />
              <p>
                Enabled sign-in methods:{' '}
                {interactive.map((p) => p.display_name).join(' · ')}
              </p>
            </div>
          )
        })()}
      </div>
    </div>
  )
}
