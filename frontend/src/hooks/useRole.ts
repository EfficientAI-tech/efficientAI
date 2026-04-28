/**
 * Role-aware hooks for the SPA.
 *
 * The auth store keeps the `role` of the current member (populated from the
 * login response and refreshed on org switch). These hooks are the canonical
 * way for components to ask "should I render this admin-only button?".
 *
 * Important: the backend is still the source of truth for security. These
 * hooks only drive UI affordances - hiding a button does not stop a
 * determined user from calling the API directly. The reader read-only
 * middleware on the backend handles that.
 */
import { useAuthStore } from '../store/authStore'
import { Role } from '../types/api'

/** Return the current member's role, or `null` if unknown / signed out. */
export function useCurrentRole(): Role | null {
  const user = useAuthStore((s) => s.user)
  if (!user?.role) return null
  const role = user.role.toLowerCase()
  if (role === Role.ADMIN || role === Role.WRITER || role === Role.READER) {
    return role as Role
  }
  return null
}

/** True when the current member is an organization admin. */
export function useIsAdmin(): boolean {
  return useCurrentRole() === Role.ADMIN
}

/**
 * True when the current member is a reader. Use this to disable / hide
 * create / edit / delete affordances on resources.
 */
export function useIsReader(): boolean {
  return useCurrentRole() === Role.READER
}

/**
 * True when the current member can mutate resources (writer or admin).
 * Convenience inverse of `useIsReader` that also handles the unknown-role
 * case conservatively (treated as not-allowed).
 */
export function useCanWrite(): boolean {
  const role = useCurrentRole()
  return role === Role.WRITER || role === Role.ADMIN
}
