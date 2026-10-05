export const TWILIO_SMS_TRIAL_BODY_TEMPLATES = [
  { value: '', label: 'Custom body (paid Twilio account)' },
  { value: 'sms_appointment_reminders', label: 'Appointment reminders (trial)' },
  { value: 'sms_customer_support', label: 'Customer support (trial)' },
  { value: 'sms_2fa', label: '2FA (trial)' },
  { value: 'sms_order_confirmation', label: 'Order confirmation (trial)' },
  { value: 'sms_delivery_updates', label: 'Delivery updates (trial)' },
  { value: 'sms_marketing_promotions', label: 'Marketing (trial)' },
  { value: 'sms_event_notifications', label: 'Event notifications (trial)' },
  { value: 'sms_account_alerts', label: 'Account alerts (trial)' },
  { value: 'sms_feedback_surveys', label: 'Feedback surveys (trial)' },
  { value: 'sms_internal_alerts', label: 'Internal alerts (trial)' },
] as const

export function trialSmsTemplateFromAgentConfig(
  cfg: Record<string, unknown> | null | undefined,
): string {
  if (!cfg || typeof cfg !== 'object') return ''
  return String(cfg.twilio_sms_trial_body_template || '').trim()
}
