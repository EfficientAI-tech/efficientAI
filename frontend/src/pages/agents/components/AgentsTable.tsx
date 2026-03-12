import { useNavigate } from 'react-router-dom'
import { Phone } from 'lucide-react'
import { TestAgent, Integration } from '../../../types/api'

interface AgentsTableProps {
  agents: TestAgent[]
  integrations: Integration[]
  selectedAgents: Set<string>
  onSelectAgent: (agentId: string, checked: boolean) => void
  onSelectAll: () => void
}

export default function AgentsTable({
  agents,
  integrations,
  selectedAgents,
  onSelectAgent,
  onSelectAll,
}: AgentsTableProps) {
  const navigate = useNavigate()

  const getIntegrationLogo = (agent: TestAgent) => {
    const integration = integrations.find((i) => i.id === agent.voice_ai_integration_id)
    if (integration?.platform === 'retell') {
      return <img src="/retellai.png" alt="Retell" className="h-5 w-5 object-contain" title="Retell AI" />
    } else if (integration?.platform === 'vapi') {
      return <img src="/vapiai.jpg" alt="Vapi" className="h-5 w-5 rounded-full object-contain" title="Vapi AI" />
    } else if (integration?.platform === 'elevenlabs') {
      return <img src="/elevenlabs.jpg" alt="ElevenLabs" className="h-5 w-5 rounded-full object-contain" title="ElevenLabs" />
    }
    return null
  }

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <input
                  type="checkbox"
                  checked={selectedAgents.size === agents.length && agents.length > 0}
                  onChange={onSelectAll}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                ID
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Name
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Call Medium
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Phone Number
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Language
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Type
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {agents.map((agent) => (
              <tr key={agent.id} className="hover:bg-gray-50">
                <td className="px-6 py-4 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selectedAgents.has(agent.id)}
                    onChange={(e) => {
                      e.stopPropagation()
                      onSelectAgent(agent.id, e.target.checked)
                    }}
                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  {agent.agent_id ? (
                    <div className="flex items-center gap-2">
                      {getIntegrationLogo(agent)}
                      <span
                        className="font-mono font-semibold text-sm text-blue-600 hover:text-blue-800 hover:underline cursor-pointer"
                        onClick={() => navigate(`/agents/${agent.agent_id || agent.id}`)}
                      >
                        {agent.agent_id}
                      </span>
                    </div>
                  ) : (
                    <span className="text-sm text-gray-400">-</span>
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center">
                    <span className="text-sm font-medium text-gray-900">{agent.name}</span>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-500 capitalize">
                      {agent.call_medium === 'phone_call' ? 'Phone Call' : 'Web Call'}
                    </span>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  {agent.call_medium === 'web_call' ? (
                    <span className="text-sm text-gray-500 italic">Not applicable</span>
                  ) : agent.phone_number ? (
                    <div className="flex items-center gap-2 text-sm text-gray-500">
                      <Phone className="w-4 h-4" />
                      {agent.phone_number}
                    </div>
                  ) : (
                    <span className="text-sm text-gray-400">-</span>
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  <span className="font-medium">{agent.language.toUpperCase()}</span>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  <span className="font-medium capitalize">{agent.call_type}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-6 py-3 bg-gray-50 border-t border-gray-200">
        <p className="text-sm text-gray-600">
          Showing {agents.length} agent{agents.length !== 1 ? 's' : ''}
        </p>
      </div>
    </div>
  )
}
