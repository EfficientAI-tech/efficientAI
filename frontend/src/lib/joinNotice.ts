const JOIN_NOTICE_KEY = 'efficientai_join_notice'

export function storeJoinNotice(message: string | null | undefined): void {
  if (!message?.trim()) return
  sessionStorage.setItem(JOIN_NOTICE_KEY, message.trim())
}

export function consumeJoinNotice(): string | null {
  const message = sessionStorage.getItem(JOIN_NOTICE_KEY)
  if (message) {
    sessionStorage.removeItem(JOIN_NOTICE_KEY)
  }
  return message
}

export function clearJoinNotice(): void {
  sessionStorage.removeItem(JOIN_NOTICE_KEY)
}
