import type { ChatConnectionType } from './ChatConnectionStep'

/** Backend pre-prod simulation leg — not shown in create wizard anymore. */
export const CHAT_PREPROD_CONNECTION_TYPE: ChatConnectionType = 'internal_llm'
export const CHAT_PREPROD_EVAL_MODE = 'pre_prod_sim' as const
export const CHAT_POSTPROD_LIVE_EVAL_MODE = 'post_prod_live' as const

const LIVE_CONNECTION_TYPES: ChatConnectionType[] = [
  'provider_chat',
  'customer_api',
  'messaging_channels',
]

export function isPreProdChatConnection(type: ChatConnectionType | string): boolean {
  return (type || CHAT_PREPROD_CONNECTION_TYPE) === 'internal_llm'
}

export function chatEvalModeForConnection(type: ChatConnectionType | string): typeof CHAT_PREPROD_EVAL_MODE | typeof CHAT_POSTPROD_LIVE_EVAL_MODE {
  return isPreProdChatConnection(type) ? CHAT_PREPROD_EVAL_MODE : CHAT_POSTPROD_LIVE_EVAL_MODE
}

export function isLiveChatConnectionType(type: ChatConnectionType | string): boolean {
  return LIVE_CONNECTION_TYPES.includes(type as ChatConnectionType)
}
