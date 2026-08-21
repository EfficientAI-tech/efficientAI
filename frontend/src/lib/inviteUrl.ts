import type { Invitation } from '../types/api'

type InviteLinkFields = Pick<Invitation, 'invite_path' | 'invite_url'>

/** Build a shareable invite URL using the current browser origin (matches blind-test sharing). */
export function buildInviteShareUrl(invitation: InviteLinkFields): string | null {
  if (invitation.invite_path) {
    return `${window.location.origin}${invitation.invite_path}`
  }
  if (!invitation.invite_url) {
    return null
  }
  try {
    const url = new URL(invitation.invite_url)
    return `${window.location.origin}${url.pathname}`
  } catch {
    return invitation.invite_url
  }
}
