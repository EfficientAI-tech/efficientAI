export type MessagingEvalChannel = 'whatsapp' | 'sms'
export type SmsCarrier = 'twilio' | 'telnyx' | null

export interface MessagingEvalProfile {
  channel: MessagingEvalChannel
  channelLabel: string
  panelSubtitle: string
  recipientLabel: string
  recipientHelper: string
  showTrialTemplate: boolean
  trialTemplateHelper: string
  testSend: 'twilio_sms' | 'telnyx_sms' | 'meta_whatsapp' | null
  testSendButtonLabel: string | null
  testSendSuccessPrefix: string
  queueRunHint: string | null
}

export function messagingChannelFromConfig(
  cfg: Record<string, unknown> | null | undefined,
): MessagingEvalChannel {
  const raw = String(cfg?.messaging_channel || 'sms').trim().toLowerCase()
  return raw === 'whatsapp' ? 'whatsapp' : 'sms'
}

export function smsCarrierFromTelephony(
  telephonyPhoneNumberId: string | null | undefined,
  numbers: { id: string; provider?: string | null }[],
): SmsCarrier {
  if (!telephonyPhoneNumberId?.trim()) return null
  const row = numbers.find((n) => n.id === telephonyPhoneNumberId)
  const provider = (row?.provider || '').toLowerCase()
  if (provider === 'telnyx') return 'telnyx'
  if (provider === 'twilio') return 'twilio'
  return null
}

export function messagingEvalProfile(args: {
  chatConnectionConfig?: Record<string, unknown> | null
  telephonyPhoneNumberId?: string | null
  smsCarrier?: SmsCarrier
}): MessagingEvalProfile {
  const channel = messagingChannelFromConfig(args.chatConnectionConfig)
  const carrier = args.smsCarrier ?? null

  if (channel === 'whatsapp') {
    return {
      channel,
      channelLabel: 'WhatsApp',
      panelSubtitle: 'Test messaging for the first combination below',
      recipientLabel: 'Recipient *',
      recipientHelper: 'E.164. Used for test sends and suite runs.',
      showTrialTemplate: false,
      trialTemplateHelper: '',
      testSend: 'meta_whatsapp',
      testSendButtonLabel: 'Test send',
      testSendSuccessPrefix: 'Message',
      queueRunHint:
        'Queue a run, then reply on WhatsApp within ~2 minutes. Your API must receive POSTs on the Meta webhook URL (Meta’s “Test webhooks” list does not call your server).',
    }
  }

  const isTwilio = carrier === 'twilio' || carrier === null
  const isTelnyx = carrier === 'telnyx'
  const carrierName = isTelnyx ? 'Telnyx' : isTwilio ? 'Twilio' : 'SMS'

  return {
    channel: 'sms',
    channelLabel: 'SMS',
    panelSubtitle: `Test ${carrierName} SMS and eval runs for the first combination below`,
    recipientLabel: 'Recipient number *',
    recipientHelper: `Same number is used for test send and when you queue suite runs.`,
    showTrialTemplate: isTwilio,
    trialTemplateHelper: 'Twilio trial only. Used when you queue runs.',
    testSend: isTelnyx ? 'telnyx_sms' : 'twilio_sms',
    testSendButtonLabel: isTelnyx ? 'Test send SMS' : 'Test send SMS',
    testSendSuccessPrefix: 'SMS',
    queueRunHint: isTelnyx
      ? 'Queue a run, then reply by SMS within ~2 minutes. Configure the inbound webhook URL (shown on the agent) in Telnyx and set the webhook public key on the Telnyx integration.'
      : 'Queue a run, then reply by SMS within ~2 minutes. Point your Twilio number’s inbound SMS webhook at the URL shown on the agent.',
  }
}

export function shouldSendTwilioTrialTemplateOnRun(profile: MessagingEvalProfile): boolean {
  return profile.channel === 'sms' && profile.showTrialTemplate
}
