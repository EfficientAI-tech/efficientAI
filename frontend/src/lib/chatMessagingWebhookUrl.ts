const API_PREFIX = '/api/v1'

function resolvePublicOrigin(publicBaseUrl?: string | null): string {
  const configured = (publicBaseUrl || '').trim().replace(/\/$/, '')
  if (configured) return configured
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin.replace(/\/$/, '')
  }
  return ''
}

/** Single platform URL — configure once on each Twilio number (Messaging → A message comes in). */
export function buildPlatformTwilioSmsInboundWebhookUrl(publicBaseUrl?: string | null): string {
  const origin = resolvePublicOrigin(publicBaseUrl)
  const path = `${API_PREFIX}/telephony/twilio/webhooks/sms-inbound`
  return origin ? `${origin}${path}` : path
}

/** Configure on the Telnyx messaging profile (all numbers on that profile). */
export function buildPlatformTelnyxSmsInboundWebhookUrl(publicBaseUrl?: string | null): string {
  const origin = resolvePublicOrigin(publicBaseUrl)
  const path = `${API_PREFIX}/telephony/telnyx/webhooks/sms-inbound`
  return origin ? `${origin}${path}` : path
}

/** @deprecated Legacy per-agent token URLs; prefer buildPlatformTwilioSmsInboundWebhookUrl. */
export function buildTwilioInboundWebhookUrl(
  webhookToken: string,
  publicBaseUrl?: string | null,
): string {
  const token = webhookToken.trim()
  if (!token) return ''
  const origin = resolvePublicOrigin(publicBaseUrl)
  const path = `${API_PREFIX}/chat/messaging/twilio/inbound/${token}`
  return origin ? `${origin}${path}` : path
}
