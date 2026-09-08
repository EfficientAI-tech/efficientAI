export const AUTH_REDIRECT_MESSAGE_KEY = 'authRedirectMessage'

export type UserSessionCredentials = {
  accessToken?: string | null
  refreshToken?: string | null
  apiKey?: string | null
}

export function getApiErrorDetail(error: unknown): string | undefined {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail
  return typeof detail === 'string' ? detail : undefined
}

export function isOrganizationAccessDenied(detail?: string): boolean {
  if (!detail) return false
  const normalized = detail.toLowerCase()
  return (
    normalized.includes('organization disabled') ||
    normalized.includes('not a member of any active organization')
  )
}

export function clearAuthSession(): void {
  localStorage.removeItem('apiKey')
  localStorage.removeItem('authUser')
  localStorage.removeItem('activeWorkspaceId')
  localStorage.removeItem('accessToken')
  localStorage.removeItem('refreshToken')
}

export function getCsrfTokenFromCookie(): string | null {
  if (typeof document === 'undefined') return null
  for (const part of document.cookie.split(';')) {
    const trimmed = part.trim()
    if (!trimmed.startsWith('eai_csrf=')) continue
    return decodeURIComponent(trimmed.slice('eai_csrf='.length))
  }
  return null
}

export function csrfHeaders(): Record<string, string> {
  const token = getCsrfTokenFromCookie()
  return token ? { 'X-CSRF-Token': token } : {}
}

/** True when a voluntary logout can still revoke something server-side. */
export function hasRevocableUserCredentials(credentials: UserSessionCredentials): boolean {
  return Boolean(credentials.accessToken || credentials.apiKey || credentials.refreshToken)
}

export function clearPlatformAdminSession(): void {
  localStorage.removeItem('platformAccessToken')
  localStorage.removeItem('platformAdminUser')
}

export function redirectToLoginWithMessage(message: string): void {
  sessionStorage.setItem(AUTH_REDIRECT_MESSAGE_KEY, message)
  clearAuthSession()
  window.location.href = '/login'
}

export function consumeAuthRedirectMessage(): string | null {
  const message = sessionStorage.getItem(AUTH_REDIRECT_MESSAGE_KEY)
  if (message) {
    sessionStorage.removeItem(AUTH_REDIRECT_MESSAGE_KEY)
  }
  return message
}

export function organizationAccessDeniedMessage(detail?: string): string {
  if (detail?.toLowerCase().includes('organization disabled')) {
    return "Your organization's access has been disabled. Contact your administrator."
  }
  return detail || "Your organization's access has been disabled. Contact your administrator."
}
