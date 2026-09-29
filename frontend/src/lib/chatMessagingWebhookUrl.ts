const API_PREFIX = '/api/v1'

export function buildTwilioInboundWebhookUrl(webhookToken: string): string {
  const token = webhookToken.trim()
  if (!token) return ''
  const origin =
    typeof window !== 'undefined' && window.location?.origin
      ? window.location.origin.replace(/\/$/, '')
      : ''
  if (!origin) return `${API_PREFIX}/chat/messaging/twilio/inbound/${token}`
  return `${origin}${API_PREFIX}/chat/messaging/twilio/inbound/${token}`
}
