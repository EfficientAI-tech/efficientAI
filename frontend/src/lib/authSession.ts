export const AUTH_REDIRECT_MESSAGE_KEY = 'authRedirectMessage'

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
  localStorage.removeItem('accessToken')
  localStorage.removeItem('refreshToken')
  localStorage.removeItem('authUser')
  localStorage.removeItem('activeWorkspaceId')
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
