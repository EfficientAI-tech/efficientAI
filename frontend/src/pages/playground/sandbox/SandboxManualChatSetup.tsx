import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import Button from '../../../components/Button'
import { sandboxApi, type AgentConfig } from '../../../lib/sandbox'
import { AgentConfigPanel } from './AgentConfigPanel'

export default function SandboxManualChatSetup() {
  const navigate = useNavigate()
  const catalog = sandboxApi.catalog()
  const [environmentId, setEnvironmentId] = useState(catalog.environments[0]?.id ?? '')
  const [agent, setAgent] = useState<AgentConfig>(() => {
    const preset = catalog.platformAgents.find((a) => a.role === 'A')
    return preset ? preset.config : sandboxApi.emptyAgentConfig('A')
  })
  const [useTestAgent, setUseTestAgent] = useState(false)
  const health = sandboxApi.healthForAgent(agent.platformAgentId)
  const missing = [
    !environmentId ? 'environment' : '',
    !agent.prompt.trim() ? 'prompt' : '',
    !agent.llm.model ? 'model' : '',
  ].filter(Boolean)

  return (
    <div className="mx-auto max-w-3xl p-6">
      <button
        type="button"
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-600"
        onClick={() => navigate('/playground?tab=sandbox')}
      >
        <ArrowLeft className="h-4 w-4" /> Back to sandbox
      </button>
      <h1 className="text-xl font-semibold text-gray-900">New manual chat</h1>
      <p className="text-sm text-gray-500">
        Chat with the main agent in a sandbox environment. The test agent is available as a secondary option.
      </p>
      <label className="mt-4 block text-sm">
        Environment
        <select
          className="mt-1 w-full rounded border px-2 py-1.5"
          value={environmentId}
          onChange={(e) => setEnvironmentId(e.target.value)}
        >
          {catalog.environments.map((env) => (
            <option key={env.id} value={env.id}>
              {env.name}
            </option>
          ))}
        </select>
      </label>
      <div className="mt-4">
        <AgentConfigPanel
          role={useTestAgent ? 'B' : 'A'}
          config={agent}
          catalog={catalog}
          health={health}
          onChange={setAgent}
          primaryTestButton={false}
        />
      </div>
      {!useTestAgent && (
        <button
          type="button"
          className="mt-3 text-xs text-gray-600 underline"
          onClick={() => {
            setUseTestAgent(true)
            const preset = catalog.platformAgents.find((a) => a.role === 'B')
            setAgent(preset ? preset.config : sandboxApi.emptyAgentConfig('B'))
          }}
        >
          Chat with the test agent instead
        </button>
      )}
      <div className="mt-6 flex justify-end">
        <Button
          disabled={missing.length > 0}
          onClick={() => {
            const session = sandboxApi.createManualChat({
              environmentId,
              agent,
              target: useTestAgent ? 'B' : 'A',
            })
            navigate(`/playground/sandbox/${session.id}`)
          }}
        >
          Start chat
        </Button>
      </div>
    </div>
  )
}
