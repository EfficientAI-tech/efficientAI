import { useState, useEffect } from 'react'
import { Plus, Phone, Edit2, Trash2 } from 'lucide-react'
import { apiClient } from '../lib/api'

interface Agent {
  id: string
  name: string
  phone_number: string
  language: string
  description: string | null
  call_type: string
  created_at: string
  updated_at: string
}

export default function Agents() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [formData, setFormData] = useState({
    name: '',
    phone_number: '',
    language: 'en',
    description: '',
    call_type: 'outbound'
  })

  useEffect(() => {
    fetchAgents()
  }, [])

  const fetchAgents = async () => {
    try {
      const data = await apiClient.listAgents()
      setAgents(data)
    } catch (error) {
      console.error('Error fetching agents:', error)
    } finally {
      setLoading(false)
    }
  }

  const createAgent = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await apiClient.createAgent({
        ...formData,
        description: formData.description || null
      })
      setShowCreateModal(false)
      setFormData({
        name: '',
        phone_number: '',
        language: 'en',
        description: '',
        call_type: 'outbound'
      })
      fetchAgents()
    } catch (error) {
      console.error('Error creating agent:', error)
    }
  }

  const deleteAgent = async (id: string) => {
    if (!confirm('Are you sure you want to delete this agent?')) return
    
    try {
      await apiClient.deleteAgent(id)
      fetchAgents()
    } catch (error) {
      console.error('Error deleting agent:', error)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading agents...</div>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Test Agents</h1>
          <p className="text-gray-600 mt-1">Manage your voice AI test agents</p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Create Agent
        </button>
      </div>

      {agents.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Phone className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No agents yet</h3>
          <p className="text-gray-500 mb-4">Create your first test agent to get started</p>
          <button
            onClick={() => setShowCreateModal(true)}
            className="text-blue-600 hover:text-blue-700 font-medium"
          >
            Create your first agent →
          </button>
        </div>
      ) : (
        <div className="grid gap-4">
          {agents.map((agent) => (
            <div
              key={agent.id}
              className="bg-white rounded-lg shadow p-6 hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-gray-900">{agent.name}</h3>
                  {agent.description && (
                    <p className="text-gray-600 mt-1">{agent.description}</p>
                  )}
                  <div className="flex gap-4 mt-3">
                    <div className="flex items-center gap-2 text-sm text-gray-500">
                      <Phone className="w-4 h-4" />
                      {agent.phone_number}
                    </div>
                    <div className="text-sm text-gray-500">
                      Language: <span className="font-medium">{agent.language.toUpperCase()}</span>
                    </div>
                    <div className="text-sm text-gray-500">
                      Type: <span className="font-medium capitalize">{agent.call_type}</span>
                    </div>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    className="p-2 text-gray-400 hover:text-blue-600 rounded-lg hover:bg-blue-50 transition-colors"
                    title="Edit"
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => deleteAgent(agent.id)}
                    className="p-2 text-gray-400 hover:text-red-600 rounded-lg hover:bg-red-50 transition-colors"
                    title="Delete"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Agent Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h2 className="text-xl font-bold text-gray-900 mb-4">Create Test Agent</h2>
            <form onSubmit={createAgent} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Name *
                </label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="Customer Support Bot"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Phone Number *
                </label>
                <input
                  type="text"
                  required
                  value={formData.phone_number}
                  onChange={(e) => setFormData({ ...formData, phone_number: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="+1234567890"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Language
                </label>
                <select
                  value={formData.language}
                  onChange={(e) => setFormData({ ...formData, language: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
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
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Call Type
                </label>
                <select
                  value={formData.call_type}
                  onChange={(e) => setFormData({ ...formData, call_type: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="outbound">Outbound</option>
                  <option value="inbound">Inbound</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Description
                </label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  rows={3}
                  placeholder="Optional description"
                />
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  Create Agent
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}