import { getApiErrorMessage } from './apiErrors'

export const ORG_REAUTH_DETAIL =
  'Sign in again with the password for that organization.'

export function isOrgReauthRequired(error: unknown): boolean {
  const err = error as { response?: { status?: number; data?: { detail?: unknown } } }
  if (err?.response?.status !== 403) {
    return false
  }
  const detail = err.response?.data?.detail
  if (typeof detail !== 'string') {
    return false
  }
  return detail.toLowerCase().includes('sign in again')
}

export function getOrgSwitchErrorMessage(error: unknown, fallback: string): string {
  if (isOrgReauthRequired(error)) {
    return ORG_REAUTH_DETAIL
  }
  return getApiErrorMessage(error, fallback)
}
