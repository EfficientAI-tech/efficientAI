import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import VoiceAgent from '../components/VoiceAgent'

const DEFAULT_PERSONA_NAMES = [
  "Grumpy Old Man",
  "Confused Senior",
  "Busy Professional",
  "Friendly Customer",
  "Angry Caller"
]

const DEFAULT_SCENARIO_NAMES = [
  "Cancel Subscription",
  "Check Balance",
  "Technical Support",
  "Make Complaint",
  "Product Inquiry"
]

export default function EvaluateTestAgents() {
  const [selectedPersona, setSelectedPersona] = useState<string>('')
  const [selectedScenario, setSelectedScenario] = useState<string>('')
  const [error] = useState<string | null>(null)

  const { data: personas = [] } = useQuery({
    queryKey: ['personas'],
    queryFn: () => apiClient.listPersonas(),
  })

  const { data: scenarios = [] } = useQuery({
    queryKey: ['scenarios'],
    queryFn: () => apiClient.listScenarios(),
  })

  const filteredPersonas = personas.filter((p: any) => !DEFAULT_PERSONA_NAMES.includes(p.name))
  const filteredScenarios = scenarios.filter((s: any) => !DEFAULT_SCENARIO_NAMES.includes(s.name))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Evaluate Test Agents</h1>
          <p className="mt-2 text-sm text-gray-600">
            Test your voice AI agents by having live conversations with test agents
          </p>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      {/* Configuration */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Configuration</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Persona
            </label>
            <select
              value={selectedPersona}
              onChange={(e) => setSelectedPersona(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
            >
              <option value="">Select a persona</option>
              {filteredPersonas.map((persona: any) => (
                <option key={persona.id} value={persona.id}>
                  {persona.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Scenario
            </label>
            <select
              value={selectedScenario}
              onChange={(e) => setSelectedScenario(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
            >
              <option value="">Select a scenario</option>
              {filteredScenarios.map((scenario: any) => (
                <option key={scenario.id} value={scenario.id}>
                  {scenario.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Voice Agent Section */}
      <div className="border-t border-gray-200 pt-6 mt-6">
        <VoiceAgent
          personaId={selectedPersona}
          scenarioId={selectedScenario}
        />
      </div>
    </div>
  )
}

