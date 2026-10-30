import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import Button from '../../../components/Button'
import { useToast } from '../../../hooks/useToast'
import {
  sandboxApi,
  type AgentConfig,
  type AgentRole,
} from '../../../lib/sandbox'
import { AgentConfigPanel } from './AgentConfigPanel'
import { SeedDataViewer } from './environmentView'
import { QuickChatDrawer } from './QuickChatDrawer'
import type { Session } from '../../../lib/sandbox'

function PolicyEditor({
  value,
  onChange,
  readOnly,
}: {
  value: string
  onChange: (v: string) => void
  readOnly?: boolean
}) {
  return (
    <textarea
      className="h-28 w-full rounded border border-gray-300 p-2 text-xs"
      value={value}
      readOnly={readOnly}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

export default function SandboxRunWizard() {
  const navigate = useNavigate()
  const { showToast, ToastContainer } = useToast()
  const catalog = sandboxApi.catalog()
  const [environmentId, setEnvironmentId] = useState(catalog.environments[0]?.id ?? '')
  const env = catalog.environments.find((e) => e.id === environmentId)
  const [policy, setPolicy] = useState(env?.policy ?? '')
  const [scenario, setScenario] = useState(
    'Fetch ENT-1001, then record that the delay was resolved.',
  )
  const [maxTurns] = useState(8)
  const [metricsSuiteId, setMetricsSuiteId] = useState(catalog.metricsSuites[0]?.id ?? '')
  const [agentA, setAgentA] = useState<AgentConfig>(sandboxApi.emptyAgentConfig('A'))
  const [agentB, setAgentB] = useState<AgentConfig>(sandboxApi.emptyAgentConfig('B'))
  const [drawerRole, setDrawerRole] = useState<AgentRole | null>(null)
  const [drawerSession, setDrawerSession] = useState<Session | undefined>()
  const [sending, setSending] = useState(false)

  const healthA = sandboxApi.healthForAgent(agentA.platformAgentId)
  const healthB = sandboxApi.healthForAgent(agentB.platformAgentId)

  const missing = useMemo(() => {
    const items: string[] = []
    if (!environmentId) items.push('environment')
    if (!agentA.prompt.trim()) items.push('Agent A prompt')
    if (!agentA.llm.model) items.push('Agent A model')
    if (!agentA.llm.credentialId) items.push('Agent A credential')
    if (!agentB.prompt.trim()) items.push('Agent B prompt')
    if (!agentB.llm.model) items.push('Agent B model')
    if (!agentB.llm.credentialId) items.push('Agent B credential')
    return items
  }, [environmentId, agentA, agentB])

  const chatReady = (config: AgentConfig) =>
    Boolean(environmentId && config.prompt.trim() && config.llm.model)

  const openChat = (role: AgentRole) => {
    const config = role === 'A' ? agentA : agentB
    if (!chatReady(config)) return
    setDrawerRole(role)
  }

  const sendDrawer = (text: string) => {
    const config = drawerRole === 'B' ? agentB : agentA
    let session = drawerSession
    if (!session) {
      session = sandboxApi.createManualChat({
        environmentId,
        agent: config,
        target: drawerRole ?? 'A',
      })
      setDrawerSession(session)
    }
    setSending(true)
    const next = sandboxApi.sendMessage({ sessionId: session.id, text })
    setDrawerSession(next)
    setSending(false)
    const newest = next.issues.find((i) => i.status === 'open')
    if (newest) showToast(`${newest.title}. View issue`, 'error')
  }

  return (
    <div className="mx-auto max-w-7xl p-6">
      <ToastContainer />
      <button
        type="button"
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-600"
        onClick={() => navigate('/playground?tab=sandbox')}
      >
        <ArrowLeft className="h-4 w-4" /> Back to sandbox
      </button>
      <h1 className="text-xl font-semibold text-gray-900">New simulation</h1>
      <p className="text-sm text-gray-500">Configure both agents, then run them in the same environment.</p>

      <div className="mt-4 space-y-3 rounded-xl border border-gray-200 bg-white p-4">
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-sm">
            Environment
            <select
              className="mt-1 w-full rounded border px-2 py-1.5"
              value={environmentId}
              onChange={(e) => {
                setEnvironmentId(e.target.value)
                const next = catalog.environments.find((envItem) => envItem.id === e.target.value)
                if (next) setPolicy(next.policy)
              }}
            >
              {catalog.environments.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {item.domain}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Metrics suite
            <select
              className="mt-1 w-full rounded border px-2 py-1.5"
              value={metricsSuiteId}
              onChange={(e) => setMetricsSuiteId(e.target.value)}
            >
              {catalog.metricsSuites.map((suite) => (
                <option key={suite.id} value={suite.id}>
                  {suite.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Max turns
            <input className="mt-1 w-full rounded border px-2 py-1.5" value={maxTurns} disabled />
          </label>
        </div>
        <label className="block text-sm">
          Trials
          <input className="mt-1 w-40 rounded border px-2 py-1.5" value={1} disabled />
          <span className="ml-2 text-xs text-gray-500">multi-trial coming soon</span>
        </label>
        <label className="block text-sm">
          Scenario (hidden from Agent A)
          <textarea
            className="mt-1 h-20 w-full rounded border p-2 text-sm"
            value={scenario}
            onChange={(e) => setScenario(e.target.value)}
          />
        </label>
        <div>
          <p className="mb-1 text-xs font-medium text-gray-500">Policy</p>
          <PolicyEditor value={policy} onChange={setPolicy} readOnly />
        </div>
        {env && <SeedDataViewer data={env.seed as Record<string, unknown>} />}
      </div>

      <div className="mt-4 flex justify-end gap-2 text-xs">
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            const a = agentA
            setAgentA(agentB)
            setAgentB(a)
          }}
        >
          Swap A and B
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setAgentB({ ...agentA, name: `${agentA.name} (copy)` })}>
          Copy A to B
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setAgentA({ ...agentB, name: `${agentB.name} (copy)` })}>
          Copy B to A
        </Button>
      </div>

      <div className="mt-2 grid gap-4 lg:grid-cols-2">
        <AgentConfigPanel
          role="A"
          config={agentA}
          catalog={catalog}
          health={healthA}
          onChange={setAgentA}
          onTestInChat={() => openChat('A')}
          testDisabledReason={!chatReady(agentA) ? 'Select an environment, prompt, and model first' : undefined}
          primaryTestButton
          onHealthClick={(badge) => badge.sessionId && navigate(`/playground/sandbox/${badge.sessionId}`)}
        />
        <AgentConfigPanel
          role="B"
          config={agentB}
          catalog={catalog}
          health={healthB}
          onChange={setAgentB}
          onTestInChat={() => openChat('B')}
          testDisabledReason={!chatReady(agentB) ? 'Select an environment, prompt, and model first' : undefined}
          onHealthClick={(badge) => badge.sessionId && navigate(`/playground/sandbox/${badge.sessionId}`)}
        />
      </div>

      <div className="sticky bottom-0 mt-6 flex items-center justify-between gap-3 border-t border-gray-200 bg-white py-3">
        <p className="text-xs text-gray-500">
          {missing.length ? `Missing: ${missing.join(', ')}` : 'Ready to run'}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => {
              const draft = sandboxApi.createSimulation({
                environmentId,
                scenario,
                maxTurns,
                metricsSuiteId,
                agentA,
                agentB,
                asDraft: true,
              })
              navigate(`/playground/sandbox/${draft.id}`)
            }}
            disabled={!environmentId}
          >
            Save as draft
          </Button>
          <Button
            disabled={missing.length > 0}
            onClick={() => {
              const session = sandboxApi.createSimulation({
                environmentId,
                scenario,
                maxTurns,
                metricsSuiteId,
                agentA,
                agentB,
              })
              navigate(`/playground/sandbox/${session.id}`)
            }}
          >
            Run simulation
          </Button>
        </div>
      </div>

      <QuickChatDrawer
        open={drawerRole != null}
        session={drawerSession}
        agent={drawerRole === 'B' ? agentB : agentA}
        sending={sending}
        onClose={() => {
          setDrawerRole(null)
          setDrawerSession(undefined)
        }}
        onOpenFull={() => drawerSession && navigate(`/playground/sandbox/${drawerSession.id}`)}
        onSend={sendDrawer}
      />
    </div>
  )
}
