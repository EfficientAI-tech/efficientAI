import { useState, useEffect } from 'react'
import { FileText, Tag } from 'lucide-react'
import { apiClient } from '../lib/api'

interface Scenario {
  id: string
  name: string
  description: string | null
  required_info: Record<string, string>
  created_at: string
  updated_at: string
}

export default function Scenarios() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchScenarios()
  }, [])

  const fetchScenarios = async () => {
    try {
      const data = await apiClient.listScenarios()
      setScenarios(data)
    } catch (error) {
      console.error('Error fetching scenarios:', error)
    } finally {
      setLoading(false)
    }
  }

  const seedDemoData = async () => {
    try {
      await apiClient.seedDemoData()
      fetchScenarios()
    } catch (error) {
      console.error('Error seeding data:', error)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading scenarios...</div>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Test Scenarios</h1>
          <p className="text-gray-600 mt-1">Pre-built conversation scenarios for testing</p>
        </div>
        {scenarios.length === 0 && (
          <button
            onClick={seedDemoData}
            className="bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700 transition-colors"
          >
            Load Demo Scenarios
          </button>
        )}
      </div>

      {scenarios.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <FileText className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No scenarios yet</h3>
          <p className="text-gray-500 mb-4">Load demo scenarios to get started with testing</p>
          <button
            onClick={seedDemoData}
            className="text-primary-600 hover:text-primary-700 font-medium"
          >
            Load demo scenarios →
          </button>
        </div>
      ) : (
        <div className="grid gap-6">
          {scenarios.map((scenario) => (
            <div
              key={scenario.id}
              className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow border border-gray-100"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <h3 className="text-xl font-bold text-gray-900 mb-2">{scenario.name}</h3>
                  {scenario.description && (
                    <p className="text-gray-600 mb-4">{scenario.description}</p>
                  )}

                  {Object.keys(scenario.required_info).length > 0 && (
                    <div className="mt-4">
                      <div className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
                        <Tag className="w-4 h-4" />
                        Required Information:
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(scenario.required_info).map(([key, value]) => (
                          <span
                            key={key}
                            className="px-3 py-1 bg-orange-50 text-orange-700 rounded-full text-sm border border-orange-100"
                          >
                            {key.replace(/_/g, ' ')}: <span className="font-mono text-xs">{value}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-4 pt-4 border-t border-gray-100 flex gap-3">
                <button className="flex-1 text-center text-sm text-primary-600 hover:text-primary-700 font-medium py-2 border border-primary-200 rounded-lg hover:bg-primary-50 transition-colors">
                  Use in Test →
                </button>
                <button className="text-sm text-gray-600 hover:text-gray-700 font-medium py-2 px-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
                  View Details
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {scenarios.length > 0 && (
        <div className="mt-6 p-4 bg-green-50 rounded-lg border border-green-100">
          <p className="text-sm text-green-800">
            💡 <strong>Tip:</strong> Scenarios define what the caller wants to accomplish. Combine them with different personas to test various conversation flows.
          </p>
        </div>
      )}
    </div>
  )
}