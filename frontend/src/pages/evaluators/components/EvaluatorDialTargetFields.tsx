import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { MODERN_INPUT_CLASS, MODERN_SELECT_CLASS } from './evaluatorUi'

interface Props {
  label: string
  value: string
  onChange: (value: string) => void
  helperText?: string
}

export default function EvaluatorDialTargetFields({ label, value, onChange, helperText }: Props) {
  const { data: dialTargets = [] } = useQuery({
    queryKey: ['telephony-dial-targets'],
    queryFn: () => apiClient.listTelephonyDialTargets(),
  })

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1.5">{label}</label>
      <input
        type="tel"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="+1234567890"
        className={MODERN_INPUT_CLASS}
      />
      {dialTargets.length > 0 && (
        <select
          className={`${MODERN_SELECT_CLASS} mt-2`}
          value=""
          onChange={(e) => e.target.value && onChange(e.target.value)}
        >
          <option value="">Contacts…</option>
          {dialTargets.map((t: { id: string; phone_number: string; label?: string | null }) => (
            <option key={t.id} value={t.phone_number}>
              {t.label || t.phone_number}
            </option>
          ))}
        </select>
      )}
      {helperText ? <p className="mt-2 text-xs text-gray-500">{helperText}</p> : null}
    </div>
  )
}
