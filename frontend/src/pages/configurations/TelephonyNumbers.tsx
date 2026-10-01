import { useMemo, useState, useEffect, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { Phone, Plus, Trash2, Users, X, Pencil } from 'lucide-react'
import Button from '../../components/Button'
import TelephonyProviderBrand from '../../components/TelephonyProviderBrand'
import { useToast } from '../../hooks/useToast'
import { useOrgTelephony } from '../../hooks/useOrgTelephony'
import {
  apiClient,
  TelephonyDialTargetResponse,
  TelephonyPhoneNumberResponse,
  TelephonyAvailableNumber,
  TelephonyImportNumbersResponse,
  PlatformOutboundPoolResponse,
  TelephonyIntegrationResponse,
} from '../../lib/api'
import {
  getTelephonyProviderDescription,
  getTelephonyProviderLabel,
} from '../../config/providers'
import { TelephonyProvider } from '../../types/api'

const IMPORT_SUPPORTED_PROVIDERS: TelephonyProvider[] = [
  TelephonyProvider.VOBIZ,
  TelephonyProvider.PLIVO,
  TelephonyProvider.EXOTEL,
  TelephonyProvider.TWILIO,
]

function telephonyIntegrationLabel(cfg: TelephonyIntegrationResponse): string {
  const provider = (cfg.provider || '') as TelephonyProvider
  const providerName = getTelephonyProviderLabel(provider)
  const custom = cfg.name?.trim()
  const base = custom ? `${providerName} — ${custom}` : `${providerName} credential`
  return cfg.is_default ? `${base} (default)` : base
}

type TelephonyTab = 'numbers' | 'contacts'

export default function TelephonyNumbers() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const { telephonyNumbers, activeConfigs, isLoading } = useOrgTelephony()
  const [activeTab, setActiveTab] = useState<TelephonyTab>('numbers')
  const [providerFilter, setProviderFilter] = useState<string>('all')
  const [showImportModal, setShowImportModal] = useState(false)
  const [importProvider, setImportProvider] = useState<TelephonyProvider>(TelephonyProvider.VOBIZ)
  const [importCredentialId, setImportCredentialId] = useState('')
  const [selectedImportNumbers, setSelectedImportNumbers] = useState<string[]>([])
  const [importResults, setImportResults] = useState<TelephonyImportNumbersResponse | null>(null)
  const [newContactPhone, setNewContactPhone] = useState('')
  const [newContactLabel, setNewContactLabel] = useState('')
  const [showContactModal, setShowContactModal] = useState(false)
  const [editingContact, setEditingContact] = useState<TelephonyDialTargetResponse | null>(null)
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
    return IMPORT_SUPPORTED_PROVIDERS.filter((provider) => configured.has(provider))
  }, [activeConfigs])

  const integrationsForImportProvider = useMemo(
    () =>
      activeConfigs.filter(
        (cfg) => (cfg.provider || '').toLowerCase() === importProvider.toLowerCase(),
      ),
    [activeConfigs, importProvider],
  )

  useEffect(() => {
    if (!showImportModal) return
    if (integrationsForImportProvider.length === 0) {
      setImportCredentialId('')
      return
    }
    const stillValid = integrationsForImportProvider.some((c) => c.id === importCredentialId)
    if (stillValid) return
    const preferred =
      integrationsForImportProvider.find((c) => c.is_default) ||
      integrationsForImportProvider[0]
    setImportCredentialId(preferred.id)
  }, [showImportModal, importProvider, integrationsForImportProvider, importCredentialId])

  const {
    data: availableNumbers = [],
    isLoading: availableNumbersLoading,
    isError: availableNumbersError,
    error: availableNumbersQueryError,
    refetch: refetchAvailableNumbers,
  } = useQuery<TelephonyAvailableNumber[]>({
    queryKey: ['telephony-available-numbers', importProvider, importCredentialId],
    queryFn: () =>
      apiClient.listAvailableTelephonyNumbers(
        importProvider,
        importCredentialId || undefined,
      ),
    enabled: showImportModal && Boolean(importCredentialId),
    retry: false,
  })

  const importNumbersMutation = useMutation({
    mutationFn: (numbers: string[]) =>
      apiClient.importTelephonyNumbers(
        importProvider,
        numbers,
        undefined,
        importCredentialId || undefined,
      ),
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
      resetContactModal()
      showToast('Contact saved', 'success')
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to save contact', 'error')
    },
  })

  const updateContactMutation = useMutation({
    mutationFn: ({
      targetId,
      data,
    }: {
      targetId: string
      data: { phone_number?: string; label?: string }
    }) => apiClient.updateDialTarget(targetId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telephony-dial-targets'] })
      resetContactModal()
      showToast('Contact updated', 'success')
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error?.message || 'Failed to update contact', 'error')
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
    setEditingContact(null)
    setNewContactPhone('')
    setNewContactLabel('')
    setShowContactModal(true)
  }

  const openEditContactModal = (contact: TelephonyDialTargetResponse) => {
    setEditingContact(contact)
    setNewContactPhone(contact.phone_number)
    setNewContactLabel(contact.label || '')
    setShowContactModal(true)
  }

  const resetContactModal = () => {
    setShowContactModal(false)
    setEditingContact(null)
    setNewContactPhone('')
    setNewContactLabel('')
  }

  const closeContactModal = () => {
    if (createContactMutation.isPending || updateContactMutation.isPending) return
    resetContactModal()
  }

  const submitContact = () => {
    const phone = newContactPhone.trim()
    if (!phone) return
    const label = newContactLabel.trim() || undefined
    if (editingContact) {
      updateContactMutation.mutate({
        targetId: editingContact.id,
        data: { phone_number: phone, label },
      })
      return
    }
    createContactMutation.mutate({ phone_number: phone, label })
  }

  const isContactModalPending = createContactMutation.isPending || updateContactMutation.isPending

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
            variant="primary"
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
              Connect a telephony provider in Integrations, import numbers here, then assign them to
              voice or messaging chat agents.
            </p>
            <div className="mt-4">
              <Button variant="primary" leftIcon={<Plus className="h-4 w-4" />} onClick={openImportModal}>
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
                      <TelephonyProviderBrand provider={number.provider} size="sm" />
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
                  return (
                    <li
                      key={`${entry.provider}:${entry.phone_number}`}
                      className="px-4 py-3 flex items-center justify-between gap-4"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <TelephonyProviderBrand
                          provider={entry.provider}
                          size="sm"
                          showLabel={false}
                        />
                        <span className="text-sm font-medium text-gray-900 truncate">{entry.phone_number}</span>
                      </div>
                      <TelephonyProviderBrand provider={entry.provider} size="sm" />
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
            <strong>Voice inbound:</strong> assign a number on the agent (Phone call → Select from provider).
          </li>
          <li>
            <strong>SMS chat:</strong> import Twilio numbers here, link on a messaging agent, set the platform
            inbound webhook on the number in Twilio Console.
          </li>
          <li>
            <strong>Outbound voice:</strong> evaluators and telephony API use org numbers or the platform pool.
          </li>
          <li>
            <strong>Contacts:</strong> saved numbers for voice outbound tests and SMS chat eval recipients.
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
              Saved numbers for voice outbound tests and SMS chat eval recipients.
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
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-gray-600 hover:text-gray-800 hover:bg-gray-100"
                      leftIcon={<Pencil className="h-4 w-4" />}
                      onClick={() => openEditContactModal(contact)}
                      aria-label={`Edit ${contact.label || contact.phone_number}`}
                    >
                      Edit
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-red-600 hover:text-red-700 hover:bg-red-50"
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
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {showContactModal &&
        renderModal(
          <div
            className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]"
            onClick={closeContactModal}
          >
            <div
              className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <h3 className="text-lg font-semibold text-gray-900">
                  {editingContact ? 'Edit contact' : 'New contact'}
                </h3>
                <button
                  type="button"
                  onClick={closeContactModal}
                  className="text-gray-400 hover:text-gray-600"
                  disabled={isContactModalPending}
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
                        submitContact()
                      }
                    }}
                  />
                </div>
                <div className="flex gap-3 pt-2">
                  <Button
                    variant="outline"
                    className="flex-1"
                    disabled={isContactModalPending}
                    onClick={closeContactModal}
                  >
                    Cancel
                  </Button>
                  <Button
                    className="flex-1"
                    disabled={!newContactPhone.trim()}
                    isLoading={isContactModalPending}
                    onClick={submitContact}
                  >
                    {editingContact ? 'Save changes' : 'Save contact'}
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
              className="bg-white rounded-lg shadow-xl max-w-xl w-full mx-4 max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-5 py-4 border-b border-gray-200 flex justify-between items-center">
                <div className="flex items-center gap-2.5 min-w-0">
                  <TelephonyProviderBrand provider={importProvider} size="sm" showLabel={false} />
                  <h3 className="text-lg font-semibold text-gray-900 truncate">Import phone numbers</h3>
                </div>
                <button
                  onClick={() => setShowImportModal(false)}
                  className="text-gray-400 hover:text-gray-600 p-1"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-5 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Provider</label>
                  {importableProviders.length === 0 ? (
                    <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
                      Connect a telephony provider in Integrations first.
                    </p>
                  ) : (
                    <>
                      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Provider">
                        {importableProviders.map((provider) => {
                          const selected = importProvider === provider
                          return (
                            <button
                              key={provider}
                              type="button"
                              role="radio"
                              aria-checked={selected}
                              onClick={() => handleImportProviderChange(provider)}
                              className={`inline-flex items-center rounded-md border px-2.5 py-1.5 text-sm transition shrink-0 ${
                                selected
                                  ? 'border-primary-500 bg-primary-50 text-primary-900 shadow-sm'
                                  : 'border-gray-200 text-gray-700 hover:border-gray-300 hover:bg-gray-50'
                              }`}
                            >
                              <TelephonyProviderBrand provider={provider} size="sm" />
                            </button>
                          )
                        })}
                      </div>
                      {getTelephonyProviderDescription(importProvider) ? (
                        <p className="text-sm text-gray-500 mt-2 leading-snug">
                          {getTelephonyProviderDescription(importProvider)}
                        </p>
                      ) : null}
                    </>
                  )}
                </div>

                {integrationsForImportProvider.length > 0 ? (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">
                      Integration credential
                    </label>
                    <div className="relative">
                      <div className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none">
                        <TelephonyProviderBrand
                          provider={importProvider}
                          size="sm"
                          showLabel={false}
                        />
                      </div>
                      <select
                        value={importCredentialId}
                        onChange={(e) => {
                          setImportCredentialId(e.target.value)
                          setSelectedImportNumbers([])
                          setImportResults(null)
                        }}
                        className="w-full pl-9 pr-2 py-2 border border-gray-300 rounded-md text-sm bg-white"
                      >
                      {integrationsForImportProvider.map((cfg) => (
                        <option key={cfg.id} value={cfg.id}>
                          {telephonyIntegrationLabel(cfg)}
                        </option>
                      ))}
                      </select>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
                    No active integration for {getTelephonyProviderLabel(importProvider)}. Add one
                    under Integrations → Telephony.
                  </p>
                )}

                {!importCredentialId ? null : availableNumbersLoading ? (
                  <p className="text-sm text-gray-600">
                    Loading numbers from {getTelephonyProviderLabel(importProvider)}...
                  </p>
                ) : availableNumbersError ? (
                  <p className="text-sm text-gray-700 border border-red-300 rounded-md px-3 py-2.5 bg-white">
                    {(availableNumbersQueryError as { response?: { data?: { detail?: string } } })
                      ?.response?.data?.detail ||
                      'Could not load numbers from this provider. Check your credentials in Settings → Integrations.'}
                  </p>
                ) : availableNumbers.length === 0 ? (
                  <p className="text-sm text-gray-600">
                    No numbers found on the connected {getTelephonyProviderLabel(importProvider)}{' '}
                    account. Connect a credential in Integrations first, or ensure the account has
                    numbers.
                  </p>
                ) : (
                  <div className="max-h-60 overflow-y-auto border border-gray-200 rounded-md divide-y divide-gray-100">
                    {availableNumbers.map((item) => {
                      const meta = [item.region, item.country].filter(Boolean).join(', ')
                      return (
                      <label
                        key={item.e164}
                        className={`flex items-center gap-2.5 px-3 py-2 text-sm ${
                          item.already_imported ? 'opacity-60 bg-gray-50/50' : 'hover:bg-gray-50 cursor-pointer'
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="shrink-0 rounded border-gray-300"
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
                        <div className="flex-1 min-w-0 flex items-baseline gap-2">
                          <span className="font-medium text-gray-900 tabular-nums">{item.e164}</span>
                          {meta ? (
                            <span className="text-sm text-gray-500 truncate">{meta}</span>
                          ) : null}
                        </div>
                        {item.already_imported && (
                          <div className="flex items-center gap-1 shrink-0">
                            <span className="text-xs text-green-700 font-medium">Imported</span>
                            {item.imported_number_id && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-red-600 hover:text-red-700 hover:bg-red-50 h-6 px-1.5 text-xs min-h-0"
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
                    )})}
                  </div>
                )}

                {importResults && (
                  <div className="rounded-lg border border-gray-200 p-3.5 space-y-2">
                    <p className="text-sm text-gray-600">
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

                <div className="flex justify-end gap-2.5 pt-2">
                  <Button variant="outline" onClick={() => setShowImportModal(false)}>
                    Close
                  </Button>
                  <Button
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
