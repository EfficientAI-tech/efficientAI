import { useEffect } from 'react'
import { PhoneOutgoing, PhoneIncoming } from 'lucide-react'
import { TelephonyProvider } from '../../../../types/api'
import { getTelephonyProviderLabel } from '../../../../config/providers'
import { useOrgTelephony } from '../../../../hooks/useOrgTelephony'
import { useAgentPhoneAssignmentCheck } from '../useAgentPhoneAssignmentCheck'
import { formatAgentPhoneConflictMessage } from '../agentPhoneValidation'
import type { CreateAgentFormData } from './createAgentTypes'

interface TelephonyBasicsStepProps {
  formData: CreateAgentFormData
  onChange: (data: CreateAgentFormData) => void
  isOpen: boolean
  phoneNumberInputMode: 'provider' | 'custom'
  onPhoneNumberInputModeChange: (mode: 'provider' | 'custom') => void
}

export default function TelephonyBasicsStep({
  formData,
  onChange,
  isOpen,
  phoneNumberInputMode,
  onPhoneNumberInputModeChange,
}: TelephonyBasicsStepProps) {
  const {
    canUseProviderNumbers,
    numbersForCallType,
  } = useOrgTelephony(isOpen)
  const telephonyNumbers = numbersForCallType(formData.call_type)
  const isTelephonyConfigError = !canUseProviderNumbers

  const { conflict: phoneConflict, isChecking: isCheckingPhoneAssignment, hasConflict: hasPhoneConflict } =
    useAgentPhoneAssignmentCheck({
      enabled: isOpen,
      callMedium: 'phone_call',
      phoneNumber: formData.phone_number,
      telephonyPhoneNumberId:
        phoneNumberInputMode === 'provider' ? formData.telephony_phone_number_id : undefined,
    })

  useEffect(() => {
    const hasProviderNumbers = canUseProviderNumbers && telephonyNumbers.length > 0
    if (!hasProviderNumbers && phoneNumberInputMode !== 'custom') {
      onPhoneNumberInputModeChange('custom')
      onChange({ ...formData, telephony_phone_number_id: '' })
      return
    }
    if (
      phoneNumberInputMode === 'provider' &&
      formData.telephony_phone_number_id &&
      !telephonyNumbers.some((n) => n.id === formData.telephony_phone_number_id && !n.agent_id)
    ) {
      onChange({ ...formData, telephony_phone_number_id: '', phone_number: '' })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    formData.call_type,
    formData.telephony_phone_number_id,
    phoneNumberInputMode,
    canUseProviderNumbers,
    telephonyNumbers,
  ])

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
        <input
          type="text"
          required
          value={formData.name}
          onChange={(e) => onChange({ ...formData, name: e.target.value })}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
          placeholder="Customer Support Bot"
        />
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <label className="block text-sm font-medium text-gray-700">Phone Number *</label>
          <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden">
            <button
              type="button"
              onClick={() => {
                onPhoneNumberInputModeChange('provider')
                onChange({ ...formData, phone_number: '' })
              }}
              disabled={!canUseProviderNumbers || telephonyNumbers.length === 0}
              className={`px-3 py-1 text-xs font-medium ${
                phoneNumberInputMode === 'provider'
                  ? 'bg-primary-600 text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-50'
              } disabled:bg-gray-100 disabled:text-gray-400`}
            >
              Select from provider
            </button>
            <button
              type="button"
              onClick={() => {
                onPhoneNumberInputModeChange('custom')
                onChange({ ...formData, telephony_phone_number_id: '' })
              }}
              className={`px-3 py-1 text-xs font-medium border-l border-gray-300 ${
                phoneNumberInputMode === 'custom'
                  ? 'bg-primary-600 text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-50'
              }`}
            >
              Enter custom
            </button>
          </div>
        </div>

        {isTelephonyConfigError && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
            No synced telephony numbers found yet. Import numbers on the Telephony Numbers page,
            configure a provider in Integrations, or enter a custom number below.
          </p>
        )}

        {phoneNumberInputMode === 'provider' ? (
          <select
            required
            value={formData.telephony_phone_number_id}
            onChange={(e) => {
              const selected = telephonyNumbers.find((n) => n.id === e.target.value)
              onChange({
                ...formData,
                telephony_phone_number_id: e.target.value,
                phone_number: selected?.phone_number || '',
              })
            }}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
            disabled={!canUseProviderNumbers || telephonyNumbers.length === 0}
          >
            <option value="">Select a synced telephony number</option>
            {telephonyNumbers.map((number) => (
              <option key={number.id} value={number.id} disabled={!!number.agent_id}>
                {number.phone_number}
                {number.provider
                  ? ` [${getTelephonyProviderLabel(number.provider as TelephonyProvider)}]`
                  : ''}
                {number.region ? ` - ${number.region}` : ''}
                {number.country_iso2 ? ` (${number.country_iso2})` : ''}
                {number.agent_id
                  ? ` [Assigned to ${number.linked_agent_name || 'another agent'}]`
                  : ''}
              </option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            required
            value={formData.phone_number}
            onChange={(e) =>
              onChange({
                ...formData,
                phone_number: e.target.value.replace(/[^\d+]/g, ''),
              })
            }
            className={`w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent ${
              hasPhoneConflict ? 'border-red-300' : 'border-gray-300'
            }`}
            placeholder="+1234567890"
          />
        )}

        {hasPhoneConflict && phoneConflict && (
          <p className="text-xs text-red-600 mt-1">
            {formatAgentPhoneConflictMessage(phoneConflict)}
          </p>
        )}
        {isCheckingPhoneAssignment && (
          <p className="text-xs text-gray-500 mt-1">Checking number availability…</p>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Language</label>
        <select
          value={formData.language}
          onChange={(e) => onChange({ ...formData, language: e.target.value })}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
        >
          <option value="en">English</option>
          <option value="es">Spanish</option>
          <option value="fr">French</option>
          <option value="de">German</option>
          <option value="zh">Chinese</option>
          <option value="hi">Hindi</option>
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Call Type *</label>
        <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden">
          {(['outbound', 'inbound'] as const).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => {
                const nextNumbers = numbersForCallType(type)
                const stillValid = nextNumbers.some((n) => n.id === formData.telephony_phone_number_id)
                onChange({
                  ...formData,
                  call_type: type,
                  ...(stillValid ? {} : { telephony_phone_number_id: '', phone_number: '' }),
                })
              }}
              className={`inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium transition-colors focus:outline-none ${
                formData.call_type === type
                  ? 'bg-primary-600 text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-50'
              } ${type === 'outbound' ? 'border-r border-gray-300' : ''}`}
            >
              {type === 'outbound' ? <PhoneOutgoing className="h-3.5 w-3.5" /> : <PhoneIncoming className="h-3.5 w-3.5" />}
              {type === 'outbound' ? 'Outbound' : 'Inbound'}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          End call after silence (seconds)
        </label>
        <input
          type="number"
          min={0}
          max={600}
          step={1}
          value={formData.silence_hangup_secs}
          onChange={(e) => {
            const parsed = parseInt(e.target.value, 10)
            onChange({
              ...formData,
              silence_hangup_secs: Number.isFinite(parsed) ? parsed : 15,
            })
          }}
          className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
        />
        <p className="mt-1 text-xs text-gray-500">
          Default 15. Set 0 to disable automatic hangup on silence.
        </p>
      </div>
    </div>
  )
}

export function validateTelephonyBasics(
  formData: CreateAgentFormData,
  phoneNumberInputMode: 'provider' | 'custom',
  isCheckingPhoneAssignment: boolean,
  hasPhoneConflict: boolean,
): boolean {
  if (!formData.name.trim()) return false
  if (phoneNumberInputMode === 'provider') {
    if (!formData.telephony_phone_number_id) return false
  } else if (!formData.phone_number?.trim()) {
    return false
  } else if (!/^[\d+]+$/.test(formData.phone_number)) {
    return false
  }
  if (isCheckingPhoneAssignment || hasPhoneConflict) return false
  return true
}
