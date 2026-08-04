import { useEffect, useState } from 'react'
import { apiClient } from '../../../lib/api'
import type { AgentPhoneAssignmentConflict } from '../../../types/api'

interface UseAgentPhoneAssignmentCheckOptions {
  enabled: boolean
  callMedium: string
  phoneNumber?: string
  telephonyPhoneNumberId?: string
  excludeAgentId?: string
  debounceMs?: number
}

export function useAgentPhoneAssignmentCheck({
  enabled,
  callMedium,
  phoneNumber,
  telephonyPhoneNumberId,
  excludeAgentId,
  debounceMs = 300,
}: UseAgentPhoneAssignmentCheckOptions) {
  const [conflict, setConflict] = useState<AgentPhoneAssignmentConflict | null>(null)
  const [isChecking, setIsChecking] = useState(false)

  useEffect(() => {
    if (!enabled || callMedium !== 'phone_call') {
      setConflict(null)
      setIsChecking(false)
      return
    }

    const trimmedPhone = phoneNumber?.trim() || ''
    const trimmedTelephonyId = telephonyPhoneNumberId?.trim() || ''
    if (!trimmedPhone && !trimmedTelephonyId) {
      setConflict(null)
      setIsChecking(false)
      return
    }

    if (trimmedPhone && trimmedPhone.length < 4 && !trimmedTelephonyId) {
      setConflict(null)
      setIsChecking(false)
      return
    }

    setIsChecking(true)
    const timer = window.setTimeout(async () => {
      try {
        const result = await apiClient.checkAgentPhoneAssignment({
          phoneNumber: trimmedPhone || undefined,
          telephonyPhoneNumberId: trimmedTelephonyId || undefined,
          excludeAgentId,
        })
        setConflict(result.available ? null : result.conflict ?? null)
      } catch {
        setConflict(null)
      } finally {
        setIsChecking(false)
      }
    }, debounceMs)

    return () => {
      window.clearTimeout(timer)
    }
  }, [
    enabled,
    callMedium,
    phoneNumber,
    telephonyPhoneNumberId,
    excludeAgentId,
    debounceMs,
  ])

  return {
    conflict,
    isChecking,
    isAvailable: !conflict,
    hasConflict: Boolean(conflict),
  }
}
