import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { Phone, Plus, Trash2, X } from 'lucide-react'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import { useOrgTelephony } from '../../hooks/useOrgTelephony'
import {
  apiClient,
  TelephonyPhoneNumberResponse,
  VobizAvailableNumber,
  VobizImportNumbersResponse,
  VobizOutboundPoolResponse,
} from '../../lib/api'
import {
  getTelephonyProviderLabel,
  getTelephonyProviderLogo,
} from '../../config/providers'
import { TelephonyProvider } from '../../types/api'

export default function TelephonyNumbers() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const { telephonyNumbers, activeConfigs, isLoading } = useOrgTelephony()
  const [providerFilter, setProviderFilter] = useState<string>('all')
  const [showVobizImportModal, setShowVobizImportModal] = useState(false)
  const [selectedVobizNumbers, setSelectedVobizNumbers] = useState<string[]>([])
  const [vobizImportResults, setVobizImportResults] = useState<VobizImportNumbersResponse | null>(null)

  const { data: outboundPool, isLoading: poolLoading } = useQuery<VobizOutboundPoolResponse>({
    queryKey: ['vobiz-outbound-pool'],
    queryFn: () => apiClient.listVobizOutboundPool(),
    retry: false,
  })

  const {
    data: vobizAvailableNumbers = [],
    isLoading: vobizNumbersLoading,
    refetch: refetchVobizNumbers,
  } = useQuery<VobizAvailableNumber[]>({
    queryKey: ['vobiz-available-numbers'],
    queryFn: () => apiClient.listVobizAvailableNumbers(),
    enabled: showVobizImportModal,
    retry: false,
  })

  const importVobizNumbersMutation = useMutation({
    mutationFn: (numbers: string[]) => apiClient.importVobizNumbers(numbers),
    onSuccess: (data) => {
      setVobizImportResults(data)
      queryClient.invalidateQueries({ queryKey: ['telephony-numbers'] })
      queryClient.invalidateQueries({ queryKey: ['vobiz-available-numbers'] })
      showToast('Vobiz numbers imported', 'success')
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to import Vobiz numbers', 'error')
    },
  })

  const providerOptions = useMemo(() => {
    const fromNumbers = telephonyNumbers
      .map((n) => n.provider)
      .filter((p): p is string => Boolean(p))
    const fromConfigs = activeConfigs.map((c) => c.provider)
    return Array.from(new Set([...fromNumbers, ...fromConfigs])).sort()
  }, [telephonyNumbers, activeConfigs])

  const filteredNumbers = useMemo(() => {
    if (providerFilter === 'all') return telephonyNumbers
    return telephonyNumbers.filter((n) => (n.provider || '').toLowerCase() === providerFilter)
  }, [telephonyNumbers, providerFilter])

  const deleteMutation = useMutation({
    mutationFn: (numberId: string) => apiClient.deleteImportedVobizNumber(numberId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telephony-numbers'] })
      showToast('Number removed from platform', 'success')
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to remove number', 'error')
    },
  })

  const canDelete = (number: TelephonyPhoneNumberResponse) =>
    (number.provider || '').toLowerCase() === TelephonyProvider.VOBIZ

  const openImportModal = () => {
    setSelectedVobizNumbers([])
    setVobizImportResults(null)
    setShowVobizImportModal(true)
    refetchVobizNumbers()
  }

  const renderModal = (content: ReactNode) => {
    if (typeof document === 'undefined') return null
    return createPortal(content, document.body)
  }

  return (
    <div className="space-y-6">
      <ToastContainer />
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Telephony Numbers</h1>
          <p className="text-gray-600 mt-1">
            Org-owned phone numbers for inbound routing and outbound caller ID.
          </p>
        </div>
        <Button variant="secondary" leftIcon={<Plus className="h-4 w-4" />} onClick={openImportModal}>
          Import numbers
        </Button>
      </div>

      <div className="bg-white rounded-lg shadow">
        <div className="px-6 py-4 border-b border-gray-200 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Phone className="h-4 w-4 text-green-600" />
            <h2 className="text-lg font-semibold text-gray-900">Number inventory</h2>
            <span className="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded-full">
              {filteredNumbers.length}
            </span>
          </div>
          <select
            value={providerFilter}
            onChange={(e) => setProviderFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
          >
            <option value="all">All providers</option>
            {providerOptions.map((provider) => (
              <option key={provider} value={provider.toLowerCase()}>
                {getTelephonyProviderLabel(provider as TelephonyProvider)}
              </option>
            ))}
          </select>
        </div>

        {isLoading ? (
          <div className="px-6 py-12 text-center text-gray-500">Loading numbers...</div>
        ) : filteredNumbers.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <Phone className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-600">No telephony numbers imported yet.</p>
            <p className="text-sm text-gray-500 mt-1">
              Connect a telephony provider in Integrations, then import numbers here and assign them
              to agents for inbound calls.
            </p>
            <div className="mt-4">
              <Button variant="secondary" size="sm" leftIcon={<Plus className="h-4 w-4" />} onClick={openImportModal}>
                Import numbers
              </Button>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Number</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Provider</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Inbound</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Outbound</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Linked agent</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {filteredNumbers.map((number) => (
                  <tr key={number.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 text-sm font-medium text-gray-900">{number.phone_number}</td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      {number.provider
                        ? getTelephonyProviderLabel(number.provider as TelephonyProvider)
                        : '—'}
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <StatusBadge enabled={number.inbound_enabled ?? true} />
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <StatusBadge enabled={number.outbound_enabled ?? true} />
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      {number.linked_agent_name || (number.agent_id ? 'Linked' : '—')}
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <span
                        className={`px-2 py-0.5 text-xs font-medium rounded ${
                          number.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {number.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right">
                      {canDelete(number) && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-red-600 hover:text-red-700 hover:bg-red-50"
                          leftIcon={<Trash2 className="h-4 w-4" />}
                          isLoading={deleteMutation.isPending && deleteMutation.variables === number.id}
                          onClick={() => deleteMutation.mutate(number.id)}
                        >
                          Remove
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="bg-white rounded-lg shadow">
        <div className="px-6 py-4 border-b border-gray-200 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            {getTelephonyProviderLogo(TelephonyProvider.VOBIZ) && (
              <img
                src={getTelephonyProviderLogo(TelephonyProvider.VOBIZ)!}
                alt="Vobiz"
                className="h-5 w-5 object-contain"
              />
            )}
            <h2 className="text-lg font-semibold text-gray-900">Platform outbound pool</h2>
            {outboundPool?.shared_across_orgs && (
              <span className="px-2 py-0.5 text-xs font-medium bg-indigo-100 text-indigo-700 rounded-full">
                Shared across all organizations
              </span>
            )}
          </div>
          {outboundPool && outboundPool.numbers.length > 0 && (
            <span className="text-xs text-gray-500">
              Max {outboundPool.max_concurrent_per_org} concurrent outbound calls per org
            </span>
          )}
        </div>
        <div className="px-6 py-4">
          {poolLoading ? (
            <p className="text-sm text-gray-500">Loading platform pool...</p>
          ) : !outboundPool || outboundPool.numbers.length === 0 ? (
            <p className="text-sm text-gray-600">
              No platform outbound pool configured. Set <code className="text-xs">vobiz.outbound_pool</code> in
              platform config to enable shared caller ID for outbound calls.
            </p>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-gray-600">
                These numbers are used as fallback caller ID when your org has no outbound-enabled numbers.
                You can also select them explicitly when placing outbound calls from an agent.
              </p>
              <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg">
                {outboundPool.numbers.map((number) => (
                  <li key={number} className="px-4 py-3 flex items-center justify-between gap-4">
                    <span className="text-sm font-medium text-gray-900">{number}</span>
                    <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded">
                      Platform pool
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="bg-blue-50 border border-blue-100 rounded-lg px-5 py-4 text-sm text-blue-900">
        <p className="font-medium">How to use these numbers</p>
        <ul className="mt-2 space-y-1 list-disc list-inside text-blue-800">
          <li>
            <strong>Inbound:</strong> assign a number to an agent (Agent → Phone call → Select from provider).
          </li>
          <li>
            <strong>Outbound:</strong> place a call from the agent detail page, or use the Vobiz outbound API.
            Caller ID uses your selection, org numbers, or the platform pool automatically.
          </li>
        </ul>
      </div>

      {showVobizImportModal &&
        renderModal(
          <div
            className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]"
            onClick={() => setShowVobizImportModal(false)}
          >
            <div
              className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <div className="flex items-center gap-2">
                  {getTelephonyProviderLogo(TelephonyProvider.VOBIZ) && (
                    <img
                      src={getTelephonyProviderLogo(TelephonyProvider.VOBIZ)!}
                      alt="Vobiz"
                      className="h-6 w-6 object-contain"
                    />
                  )}
                  <h3 className="text-lg font-semibold text-gray-900">Import Vobiz numbers</h3>
                </div>
                <button
                  onClick={() => setShowVobizImportModal(false)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6 space-y-4">
                {vobizNumbersLoading ? (
                  <p className="text-sm text-gray-600">Loading numbers from Vobiz...</p>
                ) : vobizAvailableNumbers.length === 0 ? (
                  <p className="text-sm text-gray-600">
                    No numbers found on the connected Vobiz account. Connect a Vobiz credential in
                    Integrations first, or ensure the platform account has numbers.
                  </p>
                ) : (
                  <div className="space-y-2 max-h-64 overflow-y-auto border border-gray-200 rounded-lg p-3">
                    {vobizAvailableNumbers.map((item) => (
                      <label
                        key={item.e164}
                        className={`flex items-center gap-3 p-2 rounded ${
                          item.already_imported ? 'opacity-60' : 'hover:bg-gray-50'
                        }`}
                      >
                        <input
                          type="checkbox"
                          disabled={item.already_imported}
                          checked={selectedVobizNumbers.includes(item.e164)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedVobizNumbers((prev) => [...prev, item.e164])
                            } else {
                              setSelectedVobizNumbers((prev) => prev.filter((n) => n !== item.e164))
                            }
                          }}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-gray-900">{item.e164}</div>
                          <div className="text-xs text-gray-500">
                            {[item.region, item.country].filter(Boolean).join(', ') || '—'}
                          </div>
                        </div>
                        {item.already_imported && (
                          <span className="text-xs text-green-700">Imported</span>
                        )}
                      </label>
                    ))}
                  </div>
                )}

                {vobizImportResults && (
                  <div className="rounded-lg border border-gray-200 p-3 space-y-2">
                    <p className="text-xs text-gray-600">
                      Answer URL (manual fallback):{' '}
                      <code className="break-all">{vobizImportResults.answer_url}</code>
                    </p>
                    {vobizImportResults.results.map((result) => (
                      <div
                        key={result.number}
                        className={`text-sm ${result.success ? 'text-green-700' : 'text-red-700'}`}
                      >
                        {result.number}: {result.message}
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex gap-3">
                  <Button variant="outline" className="flex-1" onClick={() => setShowVobizImportModal(false)}>
                    Close
                  </Button>
                  <Button
                    className="flex-1"
                    disabled={selectedVobizNumbers.length === 0}
                    isLoading={importVobizNumbersMutation.isPending}
                    onClick={() => importVobizNumbersMutation.mutate(selectedVobizNumbers)}
                  >
                    Import selected
                  </Button>
                </div>
              </div>
            </div>
          </div>,
        )}
    </div>
  )
}

function StatusBadge({ enabled }: { enabled: boolean }) {
  return (
    <span
      className={`px-2 py-0.5 text-xs font-medium rounded ${
        enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
      }`}
    >
      {enabled ? 'Yes' : 'No'}
    </span>
  )
}
