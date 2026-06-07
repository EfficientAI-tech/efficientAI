import type { AuthProviderConfig } from './api'

const PKCE_VERIFIER_KEY = 'oidc_code_verifier'
const PKCE_STATE_KEY = 'oidc_state'

function base64UrlEncode(buffer: ArrayBuffer | Uint8Array): string {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function generateCodeVerifier(): string {
  const buf = new Uint8Array(32)
  crypto.getRandomValues(buf)
  return base64UrlEncode(buf)
}

export async function generateCodeChallenge(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return base64UrlEncode(digest)
}

export function storePkceSession(verifier: string, state: string): void {
  sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier)
  sessionStorage.setItem(PKCE_STATE_KEY, state)
}

export function readPkceVerifier(): string | null {
  return sessionStorage.getItem(PKCE_VERIFIER_KEY)
}

export function readPkceState(): string | null {
  return sessionStorage.getItem(PKCE_STATE_KEY)
}

export function clearPkceSession(): void {
  sessionStorage.removeItem(PKCE_VERIFIER_KEY)
  sessionStorage.removeItem(PKCE_STATE_KEY)
}

async function discoverOidcEndpoints(issuer: string): Promise<{
  authorization_endpoint?: string
  token_endpoint?: string
}> {
  const discoveryUrl = `${issuer.replace(/\/$/, '')}/.well-known/openid-configuration`
  const res = await fetch(discoveryUrl)
  if (!res.ok) {
    throw new Error('Could not fetch OIDC discovery document')
  }
  return (await res.json()) as {
    authorization_endpoint?: string
    token_endpoint?: string
  }
}

export async function buildAuthorizeUrl(
  provider: AuthProviderConfig,
  redirectUri: string
): Promise<string> {
  if (!provider.oidc_client_id) {
    throw new Error('OIDC client_id is not configured')
  }

  let authorizeUrl = provider.oidc_authorize_url ?? null
  if (!authorizeUrl && provider.oidc_issuer) {
    const doc = await discoverOidcEndpoints(provider.oidc_issuer)
    authorizeUrl = doc.authorization_endpoint ?? null
  }
  if (!authorizeUrl) {
    throw new Error('Could not discover OIDC authorize endpoint')
  }

  const verifier = generateCodeVerifier()
  const challenge = await generateCodeChallenge(verifier)
  const state = crypto.randomUUID()
  storePkceSession(verifier, state)

  const params = new URLSearchParams({
    client_id: provider.oidc_client_id,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: 'openid profile email',
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  })

  return `${authorizeUrl}?${params.toString()}`
}

export async function exchangeAuthorizationCode(
  provider: AuthProviderConfig,
  code: string,
  redirectUri: string
): Promise<string> {
  if (!provider.oidc_client_id || !provider.oidc_issuer) {
    throw new Error('OIDC provider is not fully configured')
  }

  const verifier = readPkceVerifier()
  if (!verifier) {
    throw new Error('Missing PKCE verifier — try signing in again')
  }

  const doc = await discoverOidcEndpoints(provider.oidc_issuer)
  const tokenEndpoint = doc.token_endpoint
  if (!tokenEndpoint) {
    throw new Error('Could not discover OIDC token endpoint')
  }

  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: provider.oidc_client_id,
    code,
    redirect_uri: redirectUri,
    code_verifier: verifier,
  })

  const res = await fetch(tokenEndpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  })

  if (!res.ok) {
    const detail = await res.text()
    throw new Error(detail || 'Token exchange failed')
  }

  const payload = (await res.json()) as { access_token?: string }
  if (!payload.access_token) {
    throw new Error('Token response did not include access_token')
  }

  clearPkceSession()
  return payload.access_token
}
