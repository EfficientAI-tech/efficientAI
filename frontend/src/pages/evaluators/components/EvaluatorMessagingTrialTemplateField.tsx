import { MODERN_SELECT_CLASS } from './evaluatorUi'
import { TWILIO_SMS_TRIAL_BODY_TEMPLATES } from '../../../lib/twilioSmsTrialTemplates'

interface Props {
  value: string
  onChange: (value: string) => void
  helperText?: string
}

export default function EvaluatorMessagingTrialTemplateField({
  value,
  onChange,
  helperText,
}: Props) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1.5">Test message (Twilio trial)</label>
      <select
        className={MODERN_SELECT_CLASS}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {TWILIO_SMS_TRIAL_BODY_TEMPLATES.map((opt) => (
          <option key={opt.value || 'custom'} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {helperText ? <p className="mt-1.5 text-xs text-gray-500">{helperText}</p> : null}
    </div>
  )
}
