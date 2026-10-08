/** Must match backend CHAT_CONFIG_SECRET_MASK in chat_connection_config_store.py */
export const CHAT_CONFIG_SECRET_MASK = '••••••••'

const LEGACY_MASKS = new Set(['********', '••••••••'])

export function isStoredChatSecret(value: string | undefined | null): boolean {
  const trimmed = (value ?? '').trim()
  if (!trimmed) return false
  return trimmed === CHAT_CONFIG_SECRET_MASK || LEGACY_MASKS.has(trimmed)
}

/** Omit secret fields when unchanged so PUT keeps server-side ciphertext. */
export function chatSecretForPayload(value: string | undefined | null): string | undefined {
  const trimmed = (value ?? '').trim()
  if (!trimmed || isStoredChatSecret(trimmed)) return undefined
  return trimmed
}
