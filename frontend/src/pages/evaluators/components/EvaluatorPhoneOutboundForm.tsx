import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookmarkPlus, PhoneOutgoing } from 'lucide-react'
import Button from '../../../components/Button'
import { useOrgTelephony } from '../../../hooks/useOrgTelephony'
import {
  apiClient,
  TelephonyDialTargetResponse,
  VobizOutboundPoolResponse,
} from '../../../lib/api'

export interface EvaluatorPhoneOutboundFormProps {
  evaluatorId: string
  agentId: string
  personaId: string
  scenarioId: string
  personaName?: string
  scenarioName?: string
  agentPhoneNumber?: string | null
  showToast: (message: string, type: 'success' | 'error') => void
  onSuccess?: () => void
  compact?: boolean
}

export default function EvaluatorPhoneOutboundForm({
  evaluatorId,
  agentId,
  personaId,
  scenarioId,
  personaName,
  scenarioName,
  agentPhoneNumber,
  showToast,
  onSuccess,
  compact = false,
}: EvaluatorPhoneOutboundFormProps) {
  const queryClient = useQueryClient()
  const { outboundNumbers, hasTelephony } = useOrgTelephony(true)
  const [toNumber, setToNumber] = useState('')
  const [fromNumber, setFromNumber] = useState('')
  const [showSaveModal, setShowSaveModal] = useState(false)
  const [saveLabel, setSaveLabel] = useState('')

  const { data: dialTargets = [] } = useQuery<TelephonyDialTargetResponse[]>({
    queryKey: ['telephony-dial-targets'],
    queryFn: () => apiClient.listDialTargets(),
    retry: false,
  })

  const { data: outboundPool } = useQuery<VobizOutboundPoolResponse>({
    queryKey: ['vobiz-outbound-pool'],
    queryFn: () => apiClient.listVobizOutboundPool(),
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

  const normalizedToNumber = toNumber.trim()
  const isValidToNumber = /^\+[\d]+$/.test(normalizedToNumber)
  const isAlreadySaved = dialTargets.some((t) => t.phone_number === normalizedToNumber)

  const outboundMutation = useMutation({
    mutationFn: () =>
      apiClient.createVobizOutboundCall({
        agent_id: agentId,
        evaluator_id: evaluatorId,
        persona_id: personaId,
        scenario_id: scenarioId,
        to_number: normalizedToNumber,
        from_number: fromNumber.trim() || undefined,
      }),
    onSuccess: (data) => {
      showToast(
        `Outbound call initiated (${data.call_status}). Evaluate from Observability when the call completes.`,
        'success'
      )
      onSuccess?.()
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to place outbound call', 'error')
    },
  })

  const saveDialTargetMutation = useMutation({
    mutationFn: () =>
      apiClient.createDialTarget({
        phone_number: normalizedToNumber,
        label: saveLabel.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telephony-dial-targets'] })
      showToast('Number saved for your organization', 'success')
      setShowSaveModal(false)
      setSaveLabel('')
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to save number', 'error')
    },
  })

  return (
    <>
      {!compact && (personaName || scenarioName) && (
        <div className="mb-4 flex flex-wrap gap-2 text-xs">
          {personaName && (
            <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-purple-50 text-purple-800 border border-purple-200">
              Persona: {personaName}
            </span>
          )}
          {scenarioName && (
            <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-blue-50 text-blue-800 border border-blue-200">
              Scenario: {scenarioName}
            </span>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">To number *</label>
          {dialTargets.length > 0 && (
            <select
              value=""
              onChange={(e) => {
                if (e.target.value) setToNumber(e.target.value)
              }}
              className="w-full mb-2 px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm focus:ring-2 focus:ring-primary-500"
            >
              <option value="">Choose a saved number…</option>
              {dialTargets.map((target) => (
                <option key={target.id} value={target.phone_number}>
                  {target.label ? `${target.label} (${target.phone_number})` : target.phone_number}
                </option>
              ))}
            </select>
          )}
          <input
            type="text"
            value={toNumber}
            onChange={(e) => setToNumber(e.target.value.replace(/[^\d+]/g, ''))}
            placeholder="+919876543210"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
          />
          {isValidToNumber && !isAlreadySaved && (
            <button
              type="button"
              onClick={() => setShowSaveModal(true)}
              className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-800"
            >
              <BookmarkPlus className="h-3.5 w-3.5" />
              Save for later
            </button>
          )}
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

      <div className={compact ? 'mt-3' : 'mt-4'}>
        <Button
          onClick={() => outboundMutation.mutate()}
          isLoading={outboundMutation.isPending}
          disabled={!isValidToNumber}
          leftIcon={<PhoneOutgoing className="h-4 w-4" />}
        >
          Place call
        </Button>
      </div>

      {showSaveModal && (
        <div className="fixed inset-0 z-50 bg-gray-500/75 flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-lg bg-white shadow-xl p-5">
            <h4 className="text-lg font-semibold text-gray-900 mb-2">Save dial target</h4>
            <p className="text-sm text-gray-600 mb-4">
              Save <span className="font-mono">{normalizedToNumber}</span> for quick access across evaluators.
            </p>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Label <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              value={saveLabel}
              onChange={(e) => setSaveLabel(e.target.value)}
              placeholder="e.g. QA line, Staging mobile"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg mb-4 focus:ring-2 focus:ring-primary-500"
            />
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setShowSaveModal(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => saveDialTargetMutation.mutate()}
                isLoading={saveDialTargetMutation.isPending}
              >
                Save
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
