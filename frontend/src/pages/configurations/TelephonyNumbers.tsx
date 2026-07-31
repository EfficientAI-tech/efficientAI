import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { Phone, Plus, Trash2, Users, X } from 'lucide-react'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import { useOrgTelephony } from '../../hooks/useOrgTelephony'
import {
  apiClient,
  TelephonyDialTargetResponse,
  TelephonyPhoneNumberResponse,
  TelephonyAvailableNumber,
  TelephonyImportNumbersResponse,
  PlatformOutboundPoolResponse,
} from '../../lib/api'
import {
  getTelephonyProviderLabel,
  getTelephonyProviderLogo,
} from '../../config/providers'
import { TelephonyProvider } from '../../types/api'

const IMPORT_SUPPORTED_PROVIDERS: TelephonyProvider[] = [
  TelephonyProvider.VOBIZ,
  TelephonyProvider.PLIVO,
  TelephonyProvider.EXOTEL,
]

type TelephonyTab = 'numbers' | 'contacts'

function poolProviderEnum(provider: string): TelephonyProvider | null {
  const normalized = provider.toLowerCase()
  if (Object.values(TelephonyProvider).includes(normalized as TelephonyProvider)) {
    return normalized as TelephonyProvider
  }
  return null
}

function poolProviderLabel(provider: string): string {
  const known = poolProviderEnum(provider)
  if (known) return getTelephonyProviderLabel(known)
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

export default function TelephonyNumbers() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const { telephonyNumbers, activeConfigs, isLoading } = useOrgTelephony()
  const [activeTab, setActiveTab] = useState<TelephonyTab>('numbers')
  const [providerFilter, setProviderFilter] = useState<string>('all')
  const [showImportModal, setShowImportModal] = useState(false)
  const [importProvider, setImportProvider] = useState<TelephonyProvider>(TelephonyProvider.VOBIZ)
  const [selectedImportNumbers, setSelectedImportNumbers] = useState<string[]>([])
  const [importResults, setImportResults] = useState<TelephonyImportNumbersResponse | null>(null)
  const [newContactPhone, setNewContactPhone] = useState('')
  const [newContactLabel, setNewContactLabel] = useState('')
  const [showAddContactModal, setShowAddContactModal] = useState(false)
  const [numberToDelete, setNumberToDelete] = useState<TelephonyPhoneNumberResponse | null>(null)

  const { data: contacts = [], isLoading: contactsLoading } = useQuery<TelephonyDialTargetResponse[]>({
    queryKey: ['telephony-dial-targets'],
    queryFn: () => apiClient.listDialTargets(),
    retry: false,
  })

  const { data: outboundPool, isLoading: poolLoading } = useQuery<PlatformOutboundPoolResponse>({
    queryKey: ['telephony-outbound-pool'],
    queryFn: () => apiClient.listTelephonyOutboundPool(),
    retry: false,
  })

  const importableProviders = useMemo(() => {
    const configured = new Set(
      activeConfigs.map((cfg) => (cfg.provider || '').toLowerCase()).filter(Boolean),
    )
    return IMPORT_SUPPORTED_PROVIDERS.filter(
      (provider) => provider === TelephonyProvider.VOBIZ || configured.has(provider),
    )
  }, [activeConfigs])

  const {
    data: availableNumbers = [],
    isLoading: availableNumbersLoading,
    refetch: refetchAvailableNumbers,
  } = useQuery<TelephonyAvailableNumber[]>({
    queryKey: ['telephony-available-numbers', importProvider],
    queryFn: () => apiClient.listAvailableTelephonyNumbers(importProvider),
    enabled: showImportModal,
    retry: false,
  })

  const importNumbersMutation = useMutation({
    mutationFn: (numbers: string[]) =>
      apiClient.importTelephonyNumbers(importProvider, numbers),
    onSuccess: (data) => {
      setImportResults(data)
      queryClient.invalidateQueries({ queryKey: ['telephony-numbers'] })
      queryClient.invalidateQueries({ queryKey: ['telephony-available-numbers'] })
      showToast(
        `${getTelephonyProviderLabel(importProvider)} numbers imported`,
        'success',
      )
    },
    onError: (error: any) => {
      showToast(
        error?.response?.data?.detail || error?.message || 'Failed to import numbers',
        'error',
      )
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
    mutationFn: (numberId: string) => apiClient.deleteTelephonyNumber(numberId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telephony-numbers'] })
      queryClient.invalidateQueries({ queryKey: ['telephony-available-numbers'] })
      setNumberToDelete(null)
      showToast('Number removed from organization', 'success')
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to remove number', 'error')
    },
  })

  const removeImportedFromModalMutation = useMutation({
    mutationFn: (numberId: string) => apiClient.deleteTelephonyNumber(numberId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telephony-numbers'] })
      queryClient.invalidateQueries({ queryKey: ['telephony-available-numbers'] })
      refetchAvailableNumbers()
      showToast('Number removed from organization', 'success')
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to remove number', 'error')
    },
  })

  const createContactMutation = useMutation({
    mutationFn: (data: { phone_number: string; label?: string }) => apiClient.createDialTarget(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telephony-dial-targets'] })
      setNewContactPhone('')
      setNewContactLabel('')
      setShowAddContactModal(false)
      showToast('Contact saved', 'success')
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to save contact', 'error')
    },
  })

  const deleteContactMutation = useMutation({
    mutationFn: (targetId: string) => apiClient.deleteDialTarget(targetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telephony-dial-targets'] })
      showToast('Contact removed', 'success')
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to remove contact', 'error')
    },
  })

  const canDelete = (number: TelephonyPhoneNumberResponse) =>
    (number.source || 'imported') !== 'platform_pool'

  const confirmDeleteNumber = () => {
    if (numberToDelete) {
      deleteMutation.mutate(numberToDelete.id)
    }
  }

  const openImportModal = () => {
    const defaultProvider =
      importableProviders[0] ||
      (activeConfigs[0]?.provider as TelephonyProvider) ||
      TelephonyProvider.VOBIZ
    setImportProvider(defaultProvider)
    setSelectedImportNumbers([])
    setImportResults(null)
    setShowImportModal(true)
  }

  const handleImportProviderChange = (provider: TelephonyProvider) => {
    setImportProvider(provider)
    setSelectedImportNumbers([])
    setImportResults(null)
  }

  const openAddContactModal = () => {
    setNewContactPhone('')
    setNewContactLabel('')
    setShowAddContactModal(true)
  }

  const closeAddContactModal = () => {
    if (createContactMutation.isPending) return
    setShowAddContactModal(false)
    setNewContactPhone('')
    setNewContactLabel('')
  }

  const submitNewContact = () => {
    const phone = newContactPhone.trim()
    if (!phone) return
    createContactMutation.mutate({
      phone_number: phone,
      label: newContactLabel.trim() || undefined,
    })
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
        {activeTab === 'numbers' ? (
          <Button
            variant="secondary"
            leftIcon={<Plus className="h-4 w-4" />}
            onClick={openImportModal}
            disabled={importableProviders.length === 0}
          >
            Import numbers
          </Button>
        ) : (
          <Button variant="secondary" leftIcon={<Plus className="h-4 w-4" />} onClick={openAddContactModal}>
            Add contact
          </Button>
        )}
      </div>

      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6" aria-label="Telephony sections">
          <button
            type="button"
            onClick={() => setActiveTab('numbers')}
            className={`flex items-center gap-2 px-1 py-3 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
              activeTab === 'numbers'
                ? 'border-primary-600 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <Phone className="h-4 w-4" />
            Numbers
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('contacts')}
            className={`flex items-center gap-2 px-1 py-3 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
              activeTab === 'contacts'
                ? 'border-primary-600 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <Users className="h-4 w-4" />
            Contacts
            {contacts.length > 0 && (
              <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded-full">
                {contacts.length}
              </span>
            )}
          </button>
        </nav>
      </div>

      {activeTab === 'numbers' && (
        <>
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
                          onClick={() => setNumberToDelete(number)}
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
            <Phone className="h-5 w-5 text-indigo-600" />
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
              No platform outbound pool configured. Set <code className="text-xs">telephony.outbound_pool</code> in
              platform config (or legacy <code className="text-xs">vobiz.outbound_pool</code>) to enable shared caller
              ID for outbound calls across Vobiz, Plivo, Exotel, and other providers.
            </p>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-gray-600">
                These numbers are used as fallback caller ID when your org has no outbound-enabled numbers.
                You can also select them explicitly when placing outbound calls from an agent.
              </p>
              <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg">
                {outboundPool.numbers.map((entry) => {
                  const providerEnum = poolProviderEnum(entry.provider)
                  const logo = providerEnum ? getTelephonyProviderLogo(providerEnum) : null
                  return (
                    <li
                      key={`${entry.provider}:${entry.phone_number}`}
                      className="px-4 py-3 flex items-center justify-between gap-4"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        {logo ? (
                          <img
                            src={logo}
                            alt={poolProviderLabel(entry.provider)}
                            className="h-5 w-5 object-contain shrink-0"
                          />
                        ) : (
                          <Phone className="h-5 w-5 text-gray-400 shrink-0" />
                        )}
                        <span className="text-sm font-medium text-gray-900 truncate">{entry.phone_number}</span>
                      </div>
                      <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded shrink-0">
                        {poolProviderLabel(entry.provider)}
                      </span>
                    </li>
                  )
                })}
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
            <strong>Outbound:</strong> place a call from an evaluator detail page (standard evaluators with phone-call agents),
            or use the telephony outbound API. Caller ID uses your selection, org numbers, or the platform pool automatically.
          </li>
          <li>
            <strong>Contacts:</strong> save frequently called destination numbers on the Contacts tab for quick selection when placing outbound test calls.
          </li>
        </ul>
      </div>
        </>
      )}

      {activeTab === 'contacts' && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Contacts</h2>
            <p className="text-sm text-gray-600 mt-1">
              People and numbers you call often during outbound tests.
            </p>
          </div>

          {contactsLoading ? (
            <div className="px-6 py-12 text-center text-gray-500 text-sm">Loading contacts...</div>
          ) : contacts.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-gray-100">
                <Users className="h-7 w-7 text-gray-400" />
              </div>
              <p className="text-gray-900 font-medium">No contacts yet</p>
              <p className="text-sm text-gray-500 mt-1 max-w-sm mx-auto">
                Add someone you call frequently so you can pick them quickly when placing outbound test calls.
              </p>
              <div className="mt-5">
                <Button variant="secondary" leftIcon={<Plus className="h-4 w-4" />} onClick={openAddContactModal}>
                  Add contact
                </Button>
              </div>
            </div>
          ) : (
            <ul className="divide-y divide-gray-100">
              {contacts.map((contact) => (
                <li
                  key={contact.id}
                  className="flex items-center gap-4 px-6 py-4 hover:bg-gray-50 transition-colors"
                >
                  <ContactAvatar label={contact.label} phoneNumber={contact.phone_number} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {contact.label || contact.phone_number}
                    </p>
                    {contact.label && (
                      <p className="text-sm text-gray-500 truncate">{contact.phone_number}</p>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-red-600 hover:text-red-700 hover:bg-red-50 flex-shrink-0"
                    leftIcon={<Trash2 className="h-4 w-4" />}
                    isLoading={
                      deleteContactMutation.isPending &&
                      deleteContactMutation.variables === contact.id
                    }
                    onClick={() => deleteContactMutation.mutate(contact.id)}
                    aria-label={`Remove ${contact.label || contact.phone_number}`}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {showAddContactModal &&
        renderModal(
          <div
            className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]"
            onClick={closeAddContactModal}
          >
            <div
              className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <h3 className="text-lg font-semibold text-gray-900">New contact</h3>
                <button
                  type="button"
                  onClick={closeAddContactModal}
                  className="text-gray-400 hover:text-gray-600"
                  disabled={createContactMutation.isPending}
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6 space-y-4">
                <div>
                  <label htmlFor="contact-name" className="block text-sm font-medium text-gray-700 mb-1.5">
                    Name
                  </label>
                  <input
                    id="contact-name"
                    type="text"
                    value={newContactLabel}
                    onChange={(e) => setNewContactLabel(e.target.value)}
                    placeholder="e.g. QA tester"
                    autoFocus
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  />
                </div>
                <div>
                  <label htmlFor="contact-phone" className="block text-sm font-medium text-gray-700 mb-1.5">
                    Phone number
                  </label>
                  <input
                    id="contact-phone"
                    type="tel"
                    value={newContactPhone}
                    onChange={(e) => setNewContactPhone(e.target.value.replace(/[^\d+]/g, ''))}
                    placeholder="+919876543210"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && newContactPhone.trim()) {
                        submitNewContact()
                      }
                    }}
                  />
                </div>
                <div className="flex gap-3 pt-2">
                  <Button
                    variant="outline"
                    className="flex-1"
                    disabled={createContactMutation.isPending}
                    onClick={closeAddContactModal}
                  >
                    Cancel
                  </Button>
                  <Button
                    className="flex-1"
                    disabled={!newContactPhone.trim()}
                    isLoading={createContactMutation.isPending}
                    onClick={submitNewContact}
                  >
                    Save contact
                  </Button>
                </div>
              </div>
            </div>
          </div>,
        )}

      {showImportModal &&
        renderModal(
          <div
            className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]"
            onClick={() => setShowImportModal(false)}
          >
            <div
              className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <div className="flex items-center gap-2">
                  {getTelephonyProviderLogo(importProvider) && (
                    <img
                      src={getTelephonyProviderLogo(importProvider)!}
                      alt={getTelephonyProviderLabel(importProvider)}
                      className="h-6 w-6 object-contain"
                    />
                  )}
                  <h3 className="text-lg font-semibold text-gray-900">Import phone numbers</h3>
                </div>
                <button
                  onClick={() => setShowImportModal(false)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Provider</label>
                  <select
                    value={importProvider}
                    onChange={(e) =>
                      handleImportProviderChange(e.target.value as TelephonyProvider)
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
                  >
                    {importableProviders.map((provider) => (
                      <option key={provider} value={provider}>
                        {getTelephonyProviderLabel(provider)}
                      </option>
                    ))}
                  </select>
                </div>

                {availableNumbersLoading ? (
                  <p className="text-sm text-gray-600">
                    Loading numbers from {getTelephonyProviderLabel(importProvider)}...
                  </p>
                ) : availableNumbers.length === 0 ? (
                  <p className="text-sm text-gray-600">
                    No numbers found on the connected {getTelephonyProviderLabel(importProvider)}{' '}
                    account. Connect a credential in Integrations first, or ensure the account has
                    numbers.
                  </p>
                ) : (
                  <div className="space-y-2 max-h-64 overflow-y-auto border border-gray-200 rounded-lg p-3">
                    {availableNumbers.map((item) => (
                      <label
                        key={item.e164}
                        className={`flex items-center gap-3 p-2 rounded ${
                          item.already_imported ? 'opacity-60' : 'hover:bg-gray-50'
                        }`}
                      >
                        <input
                          type="checkbox"
                          disabled={item.already_imported}
                          checked={selectedImportNumbers.includes(item.e164)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedImportNumbers((prev) => [...prev, item.e164])
                            } else {
                              setSelectedImportNumbers((prev) => prev.filter((n) => n !== item.e164))
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
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-green-700">Imported</span>
                            {item.imported_number_id && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-red-600 hover:text-red-700 hover:bg-red-50 h-7 px-2"
                                isLoading={
                                  removeImportedFromModalMutation.isPending &&
                                  removeImportedFromModalMutation.variables === item.imported_number_id
                                }
                                onClick={(e) => {
                                  e.preventDefault()
                                  if (item.imported_number_id) {
                                    removeImportedFromModalMutation.mutate(item.imported_number_id)
                                  }
                                }}
                              >
                                Remove
                              </Button>
                            )}
                          </div>
                        )}
                      </label>
                    ))}
                  </div>
                )}

                {importResults && (
                  <div className="rounded-lg border border-gray-200 p-3 space-y-2">
                    <p className="text-xs text-gray-600">
                      Inbound webhook URL (manual fallback):{' '}
                      <code className="break-all">{importResults.answer_url}</code>
                    </p>
                    {importResults.results.map((result) => (
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
                  <Button variant="outline" className="flex-1" onClick={() => setShowImportModal(false)}>
                    Close
                  </Button>
                  <Button
                    className="flex-1"
                    disabled={selectedImportNumbers.length === 0}
                    isLoading={importNumbersMutation.isPending}
                    onClick={() => importNumbersMutation.mutate(selectedImportNumbers)}
                  >
                    Import selected
                  </Button>
                </div>
              </div>
            </div>
          </div>,
        )}

      {numberToDelete &&
        renderModal(
          <div
            className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]"
            onClick={() => !deleteMutation.isPending && setNumberToDelete(null)}
          >
            <div
              className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <h3 className="text-lg font-semibold text-gray-900">Remove phone number</h3>
                <button
                  onClick={() => !deleteMutation.isPending && setNumberToDelete(null)}
                  className="text-gray-400 hover:text-gray-600"
                  disabled={deleteMutation.isPending}
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6 space-y-3">
                <p className="text-sm text-gray-700">
                  Remove <span className="font-semibold text-gray-900">{numberToDelete.phone_number}</span>{' '}
                  from this organization? The number can then be imported into another organization.
                </p>
                {(numberToDelete.linked_agent_name || numberToDelete.agent_id) && (
                  <p className="text-sm text-amber-800 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                    This number is linked to{' '}
                    <span className="font-medium">
                      {numberToDelete.linked_agent_name || 'an agent'}
                    </span>
                    . Removing it will unlink the agent.
                  </p>
                )}
                <div className="flex gap-3 pt-2">
                  <Button
                    variant="outline"
                    className="flex-1"
                    disabled={deleteMutation.isPending}
                    onClick={() => setNumberToDelete(null)}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="danger"
                    className="flex-1"
                    isLoading={deleteMutation.isPending}
                    leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                    onClick={confirmDeleteNumber}
                  >
                    Remove
                  </Button>
                </div>
              </div>
            </div>
          </div>,
        )}
    </div>
  )
}

function ContactAvatar({ label, phoneNumber }: { label?: string | null; phoneNumber: string }) {
  const initials = useMemo(() => {
    const source = (label || phoneNumber).trim()
    if (!source) return '?'
    const parts = source.split(/\s+/).filter(Boolean)
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
    }
    if (label) {
      return label.slice(0, 2).toUpperCase()
    }
    const digits = phoneNumber.replace(/\D/g, '')
    return digits.slice(-2) || '?'
  }, [label, phoneNumber])

  return (
    <div
      className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full bg-primary-100 text-sm font-semibold text-primary-700"
      aria-hidden
    >
      {initials}
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
