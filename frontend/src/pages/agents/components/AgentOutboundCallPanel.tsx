import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { PhoneOutgoing } from 'lucide-react'
import Button from '../../../components/Button'
import { useOrgTelephony } from '../../../hooks/useOrgTelephony'
import { apiClient, VobizOutboundPoolResponse } from '../../../lib/api'

interface AgentOutboundCallPanelProps {
  agentId: string
  agentPhoneNumber?: string | null
  callMedium: string
  showToast: (message: string, type: 'success' | 'error') => void
}

export default function AgentOutboundCallPanel({
  agentId,
  agentPhoneNumber,
  callMedium,
  showToast,
}: AgentOutboundCallPanelProps) {
  const { outboundNumbers, hasTelephony } = useOrgTelephony(callMedium === 'phone_call')
  const [toNumber, setToNumber] = useState('')
  const [fromNumber, setFromNumber] = useState('')

  const { data: outboundPool } = useQuery<VobizOutboundPoolResponse>({
    queryKey: ['vobiz-outbound-pool'],
    queryFn: () => apiClient.listVobizOutboundPool(),
    enabled: callMedium === 'phone_call',
    retry: false,
  })

  const orgCallerIdOptions = useMemo(() => {
    const options = outboundNumbers.map((n) => n.phone_number)
    if (agentPhoneNumber && !options.includes(agentPhoneNumber)) {
      return [agentPhoneNumber, ...options]
    }
    return options
  }, [outboundNumbers, agentPhoneNumber])

  const platformPoolOptions = useMemo(() => {
    const orgSet = new Set(orgCallerIdOptions)
    return (outboundPool?.numbers || []).filter((number) => !orgSet.has(number))
  }, [outboundPool, orgCallerIdOptions])

  const outboundMutation = useMutation({
    mutationFn: () =>
      apiClient.createVobizOutboundCall({
        agent_id: agentId,
        to_number: toNumber.trim(),
        from_number: fromNumber.trim() || undefined,
      }),
    onSuccess: (data) => {
      showToast(`Outbound call initiated (${data.call_status})`, 'success')
      setToNumber('')
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to place outbound call', 'error')
    },
  })

  if (callMedium !== 'phone_call') {
    return null
  }

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center gap-2 mb-4">
        <PhoneOutgoing className="h-5 w-5 text-primary-600" />
        <h3 className="text-lg font-semibold text-gray-900">Outbound call</h3>
      </div>
      <p className="text-sm text-gray-600 mb-4">
        Place a Vobiz outbound call through this agent&apos;s Pipecat pipeline. Caller ID uses your
        selection, the agent&apos;s linked number, or the platform pool automatically.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">To number *</label>
          <input
            type="text"
            value={toNumber}
            onChange={(e) => setToNumber(e.target.value.replace(/[^\d+]/g, ''))}
            placeholder="+919876543210"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            From number <span className="text-gray-400 font-normal">(optional)</span>
          </label>
          <select
            value={fromNumber}
            onChange={(e) => setFromNumber(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500"
          >
            <option value="">Auto (agent number or platform pool)</option>
            {orgCallerIdOptions.length > 0 && (
              <optgroup label="Your numbers">
                {orgCallerIdOptions.map((number) => (
                  <option key={number} value={number}>
                    {number}
                  </option>
                ))}
              </optgroup>
            )}
            {platformPoolOptions.length > 0 && (
              <optgroup label="Platform pool">
                {platformPoolOptions.map((number) => (
                  <option key={number} value={number}>
                    {number}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </div>
      </div>

      {!hasTelephony && orgCallerIdOptions.length === 0 && platformPoolOptions.length === 0 && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2 mt-4">
          No telephony provider configured. Outbound may still work if the platform Vobiz pool is configured.
        </p>
      )}

      <div className="mt-4">
        <Button
          onClick={() => outboundMutation.mutate()}
          isLoading={outboundMutation.isPending}
          disabled={!toNumber.trim()}
          leftIcon={<PhoneOutgoing className="h-4 w-4" />}
        >
          Place call
        </Button>
      </div>
    </div>
  )
}
