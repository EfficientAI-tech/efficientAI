import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Copy, Play, Trash2 } from 'lucide-react'
import Button from '../../../components/Button'
import ConfirmModal from '../../../components/ConfirmModal'
import { useToast } from '../../../hooks/useToast'
import {
  formatDuration,
  isInProgressStatus,
  sandboxApi,
  type Issue,
  type Session,
} from '../../../lib/sandbox'
import { IssueCountChips, SandboxStatusBadge, SessionTypeBadge } from './badges'
import { ConversationView } from './conversation'
import { ConfigSnapshotView } from './configView'
import { EnvironmentTab } from './environmentView'
import { IssuesTab, SessionIssueBanner } from './issues'
import { ManualChatView } from './ManualChatView'
import { ResultsTab } from './results'
import { TracesTab } from './traces'

const TABS = ['conversation', 'issues', 'results', 'traces', 'environment', 'config'] as const
type DetailTab = (typeof TABS)[number]

export default function SandboxSessionDetail() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const { showToast, ToastContainer } = useToast()
  const [session, setSession] = useState<Session | undefined>()
  const [tab, setTab] = useState<DetailTab>('conversation')
  const [showHidden, setShowHidden] = useState(false)
  const [showDismissed, setShowDismissed] = useState(false)
  const [highlightTurn, setHighlightTurn] = useState<number>()
  const [configFocus, setConfigFocus] = useState<string>()
  const [forkOpen, setForkOpen] = useState(false)
  const [forkTurn, setForkTurn] = useState(0)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [metricsRunning, setMetricsRunning] = useState(false)

  const reload = useCallback(() => {
    if (!sessionId) return
    setSession(sandboxApi.getSession(sessionId))
  }, [sessionId])

  useEffect(() => {
    reload()
  }, [reload])

  useEffect(() => {
    if (!session || !isInProgressStatus(session.status)) return
    const id = window.setInterval(reload, 2000)
    return () => window.clearInterval(id)
  }, [session?.status, reload])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.altKey || e.metaKey)) return
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
      e.preventDefault()
      const idx = TABS.indexOf(tab)
      const next = e.key === 'ArrowRight' ? (idx + 1) % TABS.length : (idx - 1 + TABS.length) % TABS.length
      setTab(TABS[next])
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tab])

  const openIssues = useMemo(
    () => session?.issues.filter((i) => i.status === 'open') ?? [],
    [session],
  )

  const jumpIssue = (issue: Issue) => {
    setTab('conversation')
    setHighlightTurn(issue.turnIdx)
    if (issue.turnIdx != null) {
      window.setTimeout(() => {
        document.getElementById(`sandbox-turn-${issue.turnIdx}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }, 50)
    }
  }

  const fixConfig = (issue: Issue) => {
    const item = issue.configRef?.itemId
    if (!item || !issue.configRef) {
      showToast('Item no longer in config', 'error')
      setTab('config')
      return
    }
    setConfigFocus(`${issue.configRef.section}:${item}`)
    setTab('config')
    window.setTimeout(() => {
      document.getElementById(`config-${issue.configRef!.section}-${item}`)?.scrollIntoView({ behavior: 'smooth' })
    }, 50)
  }

  if (!sessionId) return null
  if (!session) {
    return (
      <div className="p-8 text-center text-sm text-gray-500">
        Session not found.{' '}
        <button type="button" className="underline" onClick={() => navigate('/playground?tab=sandbox')}>
          Back
        </button>
      </div>
    )
  }

  const isManual = session.kind === 'manual'

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
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-mono text-lg font-semibold text-gray-900">{session.id}</h1>
            <SessionTypeBadge kind={session.kind} />
            <SandboxStatusBadge status={session.status} />
            <IssueCountChips
              error={openIssues.filter((i) => i.severity === 'error').length}
              warning={openIssues.filter((i) => i.severity === 'warning').length}
              onClick={() => setTab('issues')}
            />
          </div>
          <p className="mt-1 text-sm text-gray-600">
            {session.agentA.name} ({session.agentA.llm.model})
            {session.agentB ? ` vs ${session.agentB.name} (${session.agentB.llm.model})` : ''}
            {' · '}
            {session.environment.name}
            {session.durationSeconds != null ? ` · ${formatDuration(session.durationSeconds)}` : ''}
            {session.tokens != null ? ` · ${session.tokens} tokens` : ''}
            {session.costUsd != null ? ` · $${session.costUsd.toFixed(3)}` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {session.kind === 'simulation' && (session.status === 'completed' || session.status === 'failed') && (
            <Button size="sm" variant="outline" onClick={() => {
              setForkTurn(session.turns.at(-1)?.idx ?? 0)
              setForkOpen(true)
            }}>
              Continue as manual chat
            </Button>
          )}
          {isManual && session.status !== 'ended' && session.status !== 'failed' && (
            <Button size="sm" variant="outline" onClick={() => setSession(sandboxApi.stopSession(session.id))}>
              End chat
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            leftIcon={<Copy className="h-3.5 w-3.5" />}
            onClick={() => {
              const copy = sandboxApi.duplicateSession(session.id)
              navigate(`/playground/sandbox/${copy.id}`)
            }}
          >
            Duplicate config
          </Button>
          <Button
            size="sm"
            variant="outline"
            leftIcon={<Play className="h-3.5 w-3.5" />}
            onClick={() => {
              if (session.kind === 'simulation' && session.agentB) {
                const next = sandboxApi.createSimulation({
                  environmentId: session.environment.id,
                  scenario: session.scenario ?? '',
                  maxTurns: session.maxTurns ?? 8,
                  metricsSuiteId: session.metricsSuiteId,
                  agentA: session.agentA,
                  agentB: session.agentB,
                })
                navigate(`/playground/sandbox/${next.id}`)
              }
            }}
          >
            Re-run
          </Button>
          <Button size="sm" variant="danger" leftIcon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setDeleteOpen(true)}>
            Delete
          </Button>
        </div>
      </div>

      <SessionIssueBanner issues={session.issues} onReview={() => setTab('issues')} />

      <div className="mt-4 border-b border-gray-200">
        <nav className="-mb-px flex flex-wrap gap-4" aria-label="Session tabs">
          {TABS.map((id) => (
            <button
              key={id}
              type="button"
              className={`border-b-2 py-2 text-sm capitalize ${
                tab === id ? 'border-blue-500 font-medium text-blue-600' : 'border-transparent text-gray-500'
              }`}
              onClick={() => setTab(id)}
            >
              {id}
            </button>
          ))}
        </nav>
      </div>

      <div className="mt-4">
        {tab === 'conversation' && isManual && (
          <ManualChatView
            session={session}
            sending={sending}
            onSend={(text) => {
              setSending(true)
              const before = new Set(session.issues.map((i) => i.id))
              const next = sandboxApi.sendMessage({ sessionId: session.id, text })
              setSession(next)
              setSending(false)
              const fresh = next.issues.find((i) => i.status === 'open' && !before.has(i.id))
              if (fresh) showToast(`${fresh.title}. View issue`, 'error')
            }}
            onStop={() => setSending(false)}
            onFlag={(turnIdx, note) => setSession(sandboxApi.flagMessage({ sessionId: session.id, turnIdx, note }))}
            onRegenerate={() => {
              const lastHuman = [...session.turns].reverse().find((t) => t.speaker === 'human')
              if (lastHuman) setSession(sandboxApi.sendMessage({ sessionId: session.id, text: lastHuman.text }))
            }}
            onBranch={(turn) => {
              const text = window.prompt('Edit message and resend', turn.text)
              if (text) setSession(sandboxApi.sendMessage({ sessionId: session.id, text }))
            }}
            onResetEnv={() => {
              if (window.confirm('Reset the environment to seed data?')) {
                setSession(sandboxApi.resetEnvironment(session.id))
              }
            }}
            onConfigChange={(config, summary) => setSession(sandboxApi.updateConfig(session.id, config, summary))}
            onRestart={() => {
              const next = sandboxApi.createManualChat({
                environmentId: session.environment.id,
                agent: session.chatTarget === 'B' && session.agentB ? session.agentB : session.agentA,
                target: session.chatTarget ?? 'A',
              })
              navigate(`/playground/sandbox/${next.id}`)
            }}
            onSwitchAgent={() => navigate('/playground/sandbox/new-chat')}
            onIssue={(id) => {
              const issue = session.issues.find((i) => i.id === id)
              if (issue) jumpIssue(issue)
            }}
            showDismissed={showDismissed}
            onShowDismissed={setShowDismissed}
            onDismiss={(id) => {
              const reason = window.prompt('Dismiss reason (optional)') ?? undefined
              setSession(sandboxApi.dismissIssue(session.id, id, reason || undefined))
            }}
            onRestore={(id) => setSession(sandboxApi.restoreIssue(session.id, id))}
          />
        )}
        {tab === 'conversation' && !isManual && (
          <div>
            <div className="mb-3 flex items-center justify-between">
              <label className="flex items-center gap-2 text-xs text-gray-600">
                <input type="checkbox" checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)} />
                Show hidden instruction
              </label>
              {session.status === 'running' && (
                <Button size="sm" variant="outline" onClick={() => setSession(sandboxApi.stopSession(session.id))}>
                  Stop
                </Button>
              )}
            </div>
            <ConversationView
              session={session}
              highlightTurn={highlightTurn}
              showHiddenInstruction={showHidden}
              streaming={session.status === 'running'}
              onIssue={(id) => {
                const issue = session.issues.find((i) => i.id === id)
                if (issue) {
                  setTab('issues')
                }
              }}
            />
          </div>
        )}
        {tab === 'issues' && (
          <IssuesTab
            session={session}
            showDismissed={showDismissed}
            onShowDismissed={setShowDismissed}
            onViewConversation={jumpIssue}
            onViewTrace={(issue) => {
              setTab('traces')
              showToast(`Opened traces for ${issue.title}`, 'success')
            }}
            onFixConfig={fixConfig}
            onDismiss={(issue) => {
              const reason = window.prompt('Dismiss reason (optional)') ?? undefined
              setSession(sandboxApi.dismissIssue(session.id, issue.id, reason || undefined))
            }}
            onRestore={(issue) => setSession(sandboxApi.restoreIssue(session.id, issue.id))}
          />
        )}
        {tab === 'results' && (
          <ResultsTab
            session={session}
            running={metricsRunning}
            onRunMetrics={() => {
              setMetricsRunning(true)
              window.setTimeout(() => {
                setSession(sandboxApi.runMetrics(session.id))
                setMetricsRunning(false)
              }, 400)
            }}
            onReEvaluate={() => {
              setMetricsRunning(true)
              window.setTimeout(() => {
                setSession(sandboxApi.runMetrics(session.id))
                setMetricsRunning(false)
              }, 400)
            }}
          />
        )}
        {tab === 'traces' && (
          <TracesTab
            session={session}
            onJumpIssue={(id) => {
              const issue = session.issues.find((i) => i.id === id)
              if (issue) jumpIssue(issue)
            }}
          />
        )}
        {tab === 'environment' && (
          <EnvironmentTab
            session={session}
            onJumpTurn={(idx) => {
              setHighlightTurn(idx)
              setTab('conversation')
            }}
          />
        )}
        {tab === 'config' && (
          <ConfigSnapshotView
            session={session}
            focus={configFocus}
            onDuplicate={() => navigate('/playground/sandbox/new')}
          />
        )}
      </div>

      <ConfirmModal
        isOpen={forkOpen}
        title="Continue as manual chat"
        description="Fork this run from a chosen turn. You will talk to the main agent from that environment state."
        confirmLabel="Fork"
        onCancel={() => setForkOpen(false)}
        onConfirm={() => {
          const forked = sandboxApi.forkSession(session.id, forkTurn)
          setForkOpen(false)
          navigate(`/playground/sandbox/${forked.id}`)
        }}
      >
        <label className="mt-2 block text-sm">
          Start from turn
          <input
            type="number"
            className="mt-1 w-full rounded border px-2 py-1"
            value={forkTurn}
            onChange={(e) => setForkTurn(Number(e.target.value))}
          />
        </label>
      </ConfirmModal>
      <ConfirmModal
        isOpen={deleteOpen}
        title="Delete this session?"
        variant="danger"
        confirmLabel="Delete"
        onCancel={() => setDeleteOpen(false)}
        onConfirm={() => {
          sandboxApi.deleteSession(session.id)
          navigate('/playground?tab=sandbox')
        }}
      />
    </div>
  )
}
