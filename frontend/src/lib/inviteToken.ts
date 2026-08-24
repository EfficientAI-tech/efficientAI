export const PENDING_INVITE_TOKEN_KEY = 'pendingInviteToken'

export function storePendingInviteToken(token: string): void {
  sessionStorage.setItem(PENDING_INVITE_TOKEN_KEY, token)
}

export function getPendingInviteToken(): string | null {
  return sessionStorage.getItem(PENDING_INVITE_TOKEN_KEY)
}

export function consumePendingInviteToken(): string | null {
  const token = sessionStorage.getItem(PENDING_INVITE_TOKEN_KEY)
  if (token) {
    sessionStorage.removeItem(PENDING_INVITE_TOKEN_KEY)
  }
  return token
}

export function clearPendingInviteToken(): void {
  sessionStorage.removeItem(PENDING_INVITE_TOKEN_KEY)
}
