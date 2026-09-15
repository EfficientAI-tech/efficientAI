import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '../store/authStore'
import { getApiErrorMessage } from '../lib/apiErrors'
import { isOrgReauthRequired } from '../lib/orgReauth'

type ReauthTarget = {
  id: string
  name: string
}

export function useOrgSwitch() {
  const { switchOrg, reauthForOrg, user } = useAuthStore()
  const queryClient = useQueryClient()
  const [switchingTo, setSwitchingTo] = useState<string | null>(null)
  const [reauthTarget, setReauthTarget] = useState<ReauthTarget | null>(null)
  const [reauthError, setReauthError] = useState('')
  const [reauthLoading, setReauthLoading] = useState(false)
  const [error, setError] = useState('')

  const switchToOrg = async (orgId: string, orgName?: string) => {
    setError('')
    setSwitchingTo(orgId)
    try {
      await switchOrg(orgId)
      await queryClient.invalidateQueries()
      return true
    } catch (err: unknown) {
      if (isOrgReauthRequired(err)) {
        setReauthTarget({
          id: orgId,
          name: orgName || 'this organization',
        })
        setReauthError('')
        return false
      }
      setError(getApiErrorMessage(err, 'Could not switch organization'))
      return false
    } finally {
      setSwitchingTo(null)
    }
  }

  const closeReauth = () => {
    if (reauthLoading) return
    setReauthTarget(null)
    setReauthError('')
  }

  const submitReauth = async (password: string) => {
    if (!reauthTarget) return
    setReauthError('')
    setReauthLoading(true)
    try {
      await reauthForOrg(reauthTarget.id, password)
      await queryClient.invalidateQueries()
      setReauthTarget(null)
      return true
    } catch (err: unknown) {
      setReauthError(getApiErrorMessage(err, 'Invalid password'))
      return false
    } finally {
      setReauthLoading(false)
    }
  }

  return {
    user,
    switchingTo,
    error,
    setError,
    reauthTarget,
    reauthError,
    reauthLoading,
    switchToOrg,
    closeReauth,
    submitReauth,
  }
}
