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
      recipientHelper: 'E.164 used for test send and suite runs.',
      showTrialTemplate: false,
      trialTemplateHelper: '',
      testSend: 'meta_whatsapp',
      testSendButtonLabel: 'Test send',
      testSendSuccessPrefix: 'Message',
    }
  }

  const isTwilio = carrier === 'twilio' || carrier === null
  const isTelnyx = carrier === 'telnyx'
  const carrierName = isTelnyx ? 'Telnyx' : isTwilio ? 'Twilio' : 'SMS'

  return {
    channel: 'sms',
    channelLabel: 'SMS',
    panelSubtitle: `Test ${carrierName} SMS for the first combination below`,
    recipientLabel: 'Recipient number *',
    recipientHelper: 'Same number for test send and suite runs.',
    showTrialTemplate: isTwilio,
    trialTemplateHelper: 'Twilio trial only. Used when you queue runs.',
    testSend: isTelnyx ? 'telnyx_sms' : 'twilio_sms',
    testSendButtonLabel: 'Test send SMS',
    testSendSuccessPrefix: 'SMS',
  }
}

export function shouldSendTwilioTrialTemplateOnRun(profile: MessagingEvalProfile): boolean {
  return profile.channel === 'sms' && profile.showTrialTemplate
}
