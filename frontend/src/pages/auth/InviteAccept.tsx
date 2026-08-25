import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AlertCircle, Building2, Eye, EyeOff, Loader2 } from 'lucide-react'
import { Card, CardBody, Tabs, Tab } from '@heroui/react'
import Logo from '../../components/Logo'
import Button from '../../components/Button'
import { apiClient, isLoginOrgSelectionResponse } from '../../lib/api'
import type { AuthConfigResponse, AuthProviderConfig } from '../../lib/api'
import type { InvitationPreview } from '../../types/api'
import { useAuthStore } from '../../store/authStore'
import { buildAuthorizeUrl } from '../../lib/oidc'
import { PASSWORD_POLICY_HINT, validatePasswordPolicy } from '../../lib/passwordPolicy'
import { storePendingInviteToken } from '../../lib/inviteToken'

type Mode = 'signup' | 'password' | 'sso'

const TAB_CLASS_NAMES = {
  base: 'mb-4',
  tabList: 'w-full bg-gray-100 p-1 rounded-full',
  tab: 'flex-1 h-10 px-3 data-[hover=true]:opacity-100',
  cursor: 'bg-[#fef08a] border border-[#facc15] shadow-sm rounded-full',
  tabContent: 'text-sm font-medium text-gray-500 group-data-[selected=true]:text-[#854d0e]',
}

const INPUT_CLASS =
  'w-full px-4 py-3 text-base text-gray-900 bg-gray-50 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-[#ca8a04] focus:bg-white'

function FormError({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex w-full items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-relaxed text-red-700"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
      <p className="min-w-0 flex-1 whitespace-normal break-words">{message}</p>
    </div>
  )
}

function InvitePageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-amber-50 via-yellow-50 to-orange-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-primary-200 rounded-full mix-blend-multiply filter blur-xl opacity-30 animate-pulse" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-orange-200 rounded-full mix-blend-multiply filter blur-xl opacity-30 animate-pulse" />
      </div>
      <div className="max-w-md w-full space-y-8 relative z-10">{children}</div>
    </div>
  )
}

export default function InviteAccept() {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const { user, accessToken, setSession, logout } = useAuthStore()

  const [preview, setPreview] = useState<InvitationPreview | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(true)
  const [previewError, setPreviewError] = useState('')
  const [authConfig, setAuthConfig] = useState<AuthConfigResponse | null>(null)
  const [mode, setMode] = useState<Mode>('signup')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [accepting, setAccepting] = useState(false)
  const [autoAcceptFailed, setAutoAcceptFailed] = useState(false)

  useEffect(() => {
    if (!token) {
      setPreviewError('Invalid invitation link')
      setLoadingPreview(false)
      return
    }

    storePendingInviteToken(token)

    let active = true
    Promise.all([apiClient.previewInvitation(token), apiClient.getAuthConfig()])
      .then(([previewData, cfg]) => {
        if (!active) return
        setPreview(previewData)
        setEmail(previewData.email)
        setAuthConfig(cfg)
        setMode(previewData.has_password ? 'password' : 'signup')
        if (previewData.status !== 'pending') {
          setPreviewError(
            previewData.status === 'expired'
              ? 'This invitation has expired. Ask your administrator to send a new one.'
              : 'This invitation is no longer valid.',
          )
        }
      })
      .catch((err: any) => {
        if (!active) return
        setPreviewError(err?.response?.data?.detail || 'Invitation not found')
      })
      .finally(() => active && setLoadingPreview(false))

    return () => {
      active = false
    }
  }, [token])

  useEffect(() => {
    if (!token || !preview || preview.status !== 'pending' || !accessToken || !user) {
      return
    }

    if (user.email.toLowerCase() !== preview.email.toLowerCase()) {
      setPreviewError(
        `You're signed in as ${user.email}, but this invitation was sent to ${preview.email}. Sign out to continue with the invited account.`,
      )
      return
    }

    let active = true
    setAccepting(true)
    apiClient
      .acceptInvitationByToken(token)
      .then((res) => {
        if (!active) return
        setSession(res.access_token, res.user, res.refresh_token)
        navigate('/', { replace: true })
      })
      .catch((err: any) => {
        if (!active) return
        setAutoAcceptFailed(true)
        logout()
        setError(err?.response?.data?.detail || 'Could not accept invitation')
      })
      .finally(() => active && setAccepting(false))

    return () => {
      active = false
    }
  }, [token, preview, accessToken, user, setSession, navigate])

  const localPwd = authConfig?.providers.find((p) => p.name === 'local_password' && p.enabled)
  const oidc = authConfig?.providers.find((p) => p.name === 'external_oidc' && p.enabled)

  const tabs = useMemo(() => {
    const items: Array<{ key: Mode; label: string }> = []
    const canSignUp = localPwd?.supports_signup && !preview?.has_password
    const canSignIn = !!localPwd && preview?.has_password

    if (canSignUp) {
      items.push({ key: 'signup', label: 'Create account' })
    }
    if (canSignIn) {
      items.push({ key: 'password', label: 'Sign in' })
    }
    if (oidc) {
      items.push({ key: 'sso', label: 'SSO' })
    }
    return items
  }, [preview?.has_password, localPwd, oidc])

  useEffect(() => {
    if (tabs.length === 0) return
    if (!tabs.some((tab) => tab.key === mode)) {
      setMode(tabs[0].key)
    }
  }, [tabs, mode])

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token) return
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
        first_name: firstName || undefined,
        last_name: lastName || undefined,
        invite_token: token,
      })
      setSession(res.access_token, res.user, res.refresh_token)
      navigate('/', { replace: true })
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Sign up failed')
    } finally {
      setIsLoading(false)
    }
  }

  const handlePasswordLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token) return
    setError('')
    setIsLoading(true)
    try {
      const res = await apiClient.loginWithPassword(email, password, undefined, token)
      if (isLoginOrgSelectionResponse(res)) {
        setError('Multiple organizations found. Accept the invitation from your profile after signing in.')
        return
      }
      const accepted = await apiClient.acceptInvitationByToken(token)
      setSession(accepted.access_token, accepted.user, accepted.refresh_token)
      navigate('/', { replace: true })
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Sign in failed')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSsoRedirect = async (provider: AuthProviderConfig) => {
    if (!token || !provider.oidc_client_id) {
      setError('SSO is not fully configured on this server.')
      return
    }
    storePendingInviteToken(token)
    try {
      const redirect = `${window.location.origin}/login/callback`
      const authorizeUrl = await buildAuthorizeUrl(provider, redirect)
      window.location.href = authorizeUrl
    } catch (err: any) {
      setError(err?.message || 'Could not start SSO sign-in')
    }
  }

  if (loadingPreview || accepting) {
    return (
      <InvitePageShell>
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-600">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-sm">{accepting ? 'Accepting invitation…' : 'Loading invitation…'}</p>
        </div>
      </InvitePageShell>
    )
  }

  const orgName = preview?.organization_name || 'your organization'
  const roleLabel = preview?.role || 'member'
  const showAuthForms =
    !previewError &&
    preview?.status === 'pending' &&
    (!accessToken || autoAcceptFailed)

  return (
    <InvitePageShell>
      <div className="text-center">
        <div className="flex justify-center mb-4">
          <Logo textSize="xl" />
        </div>
        <h1 className="text-lg font-semibold text-gray-900">You're invited</h1>
        <p className="mt-2 text-sm text-gray-600">
          Join <span className="font-medium text-gray-900">{orgName}</span> as{' '}
          <span className="capitalize">{roleLabel}</span>
        </p>
      </div>

      <Card className="shadow-xl">
        <CardBody className="p-6">
          {preview && !previewError && preview.has_password && showAuthForms && (
            <div className="mb-4 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
              An account already exists for <span className="font-medium">{preview.email}</span>.
              Sign in below to join {orgName} — you don&apos;t need to create a new account.
            </div>
          )}

          {preview && !previewError && (
            <div className="mb-4 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <Building2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <p className="text-left">
                Invitation for <span className="font-medium">{preview.email}</span>
                {preview.expires_at && (
                  <> · expires {new Date(preview.expires_at).toLocaleDateString()}</>
                )}
              </p>
            </div>
          )}

          {previewError && <FormError message={previewError} />}

          {previewError && accessToken && user && (
            <div className="mt-4">
              <Button
                variant="outline"
                size="lg"
                className="w-full"
                onClick={() => {
                  logout()
                  setPreviewError('')
                  window.location.reload()
                }}
              >
                Sign out and continue
              </Button>
            </div>
          )}

          {error && !showAuthForms && (
            <div className="mt-4">
              <FormError message={error} />
            </div>
          )}

          {showAuthForms && (
            <>
              {tabs.length > 1 && (
                <Tabs
                  aria-label="Invitation sign-in methods"
                  selectedKey={mode}
                  onSelectionChange={(k) => {
                    setMode(k as Mode)
                    setError('')
                    setShowPassword(false)
                  }}
                  variant="solid"
                  radius="full"
                  fullWidth
                  classNames={TAB_CLASS_NAMES}
                >
                  {tabs.map((tab) => (
                    <Tab key={tab.key} title={tab.label} />
                  ))}
                </Tabs>
              )}

              {mode === 'signup' && localPwd?.supports_signup && !preview?.has_password && (
                <form onSubmit={handleSignup} className="space-y-4">
                  <div className="grid grid-cols-2 gap-2">
                    <input
                      type="text"
                      placeholder="First name"
                      value={firstName}
                      onChange={(e) => setFirstName(e.target.value)}
                      className={INPUT_CLASS}
                    />
                    <input
                      type="text"
                      placeholder="Last name"
                      value={lastName}
                      onChange={(e) => setLastName(e.target.value)}
                      className={INPUT_CLASS}
                    />
                  </div>
                  <input
                    type="email"
                    value={email}
                    readOnly
                    aria-readonly
                    className="w-full px-4 py-3 text-base text-gray-700 bg-gray-100 border-2 border-gray-200 rounded-xl"
                  />
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
                      className={`${INPUT_CLASS} pr-12`}
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
                  <Button type="submit" variant="primary" size="lg" isLoading={isLoading} className="w-full">
                    Create account and join
                  </Button>
                  {error && <FormError message={error} />}
                  <p className="text-xs text-gray-500 text-center">
                    You'll join {orgName} directly — no separate organization is created.
                  </p>
                </form>
              )}

              {mode === 'password' && localPwd && preview?.has_password && (
                <form onSubmit={handlePasswordLogin} className="space-y-4">
                  <input
                    type="email"
                    value={email}
                    readOnly
                    aria-readonly
                    className="w-full px-4 py-3 text-base text-gray-700 bg-gray-100 border-2 border-gray-200 rounded-xl"
                  />
                  <div className="relative">
                    <input
                      type={showPassword ? 'text' : 'password'}
                      placeholder="Password"
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      className={`${INPUT_CLASS} pr-12`}
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
                  <Button type="submit" variant="primary" size="lg" isLoading={isLoading} className="w-full">
                    Sign in and join
                  </Button>
                  {error && <FormError message={error} />}
                </form>
              )}

              {mode === 'sso' && oidc && (
                <div className="space-y-4">
                  <Button
                    variant="outline"
                    size="lg"
                    className="w-full"
                    onClick={() => handleSsoRedirect(oidc)}
                  >
                    Continue with {oidc.display_name}
                  </Button>
                  {error && <FormError message={error} />}
                  <p className="text-xs text-gray-500 text-center">
                    After SSO, you'll be added to {orgName} automatically.
                  </p>
                </div>
              )}
            </>
          )}
        </CardBody>
      </Card>
    </InvitePageShell>
  )
}
