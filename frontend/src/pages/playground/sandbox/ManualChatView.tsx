import { useState } from 'react'
import { Copy, Flag, RefreshCw, Split } from 'lucide-react'
import Button from '../../../components/Button'
import ConfirmModal from '../../../components/ConfirmModal'
import type { AgentConfig, Session, Turn } from '../../../lib/sandbox'
import { ConversationView } from './conversation'
import { IssuesTab } from './issues'
import { SeedDataViewer } from './environmentView'
import { RoleBadge } from './badges'

export function ChatComposer({
  disabled,
  sending,
  onSend,
  onStop,
}: {
  disabled?: boolean
  sending?: boolean
  onSend: (text: string) => void
  onStop?: () => void
}) {
  const [text, setText] = useState('')
  return (
    <form
      className="border-t border-gray-200 p-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (!text.trim() || sending) return
        onSend(text.trim())
        setText('')
      }}
    >
      <textarea
        className="w-full rounded-lg border border-gray-300 p-2 text-sm"
        rows={3}
        value={text}
        disabled={disabled}
        placeholder="Message the agent"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            if (text.trim() && !sending) {
              onSend(text.trim())
              setText('')
            }
          }
        }}
      />
      <div className="mt-2 flex items-center justify-between">
        <p className="text-[11px] text-gray-500">Press Enter to send, Shift+Enter for newline</p>
        {sending ? (
          <Button size="sm" variant="outline" onClick={onStop}>
            Stop
          </Button>
        ) : (
          <Button size="sm" type="submit" disabled={disabled || !text.trim()}>
            Send
          </Button>
        )}
      </div>
    </form>
  )
}

function MessageActions({
  turn,
  onRegenerate,
  onBranch,
  onCopy,
  onFlag,
}: {
  turn: Turn
  onRegenerate?: () => void
  onBranch?: () => void
  onCopy?: () => void
  onFlag?: () => void
}) {
  if (turn.divider) return null
  return (
    <div className="flex justify-end gap-1">
      {turn.speaker !== 'human' && onRegenerate && (
        <button type="button" className="rounded p-1 text-gray-400 hover:bg-gray-100" onClick={onRegenerate} title="Regenerate">
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      )}
      {turn.speaker === 'human' && onBranch && (
        <button type="button" className="rounded p-1 text-gray-400 hover:bg-gray-100" onClick={onBranch} title="Edit and branch">
          <Split className="h-3.5 w-3.5" />
        </button>
      )}
      {onCopy && (
        <button type="button" className="rounded p-1 text-gray-400 hover:bg-gray-100" onClick={onCopy} title="Copy">
          <Copy className="h-3.5 w-3.5" />
        </button>
      )}
      {turn.speaker !== 'human' && onFlag && (
        <button type="button" className="rounded p-1 text-gray-400 hover:bg-gray-100" onClick={onFlag} title="Flag as wrong">
          <Flag className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}

export function LiveInspector({
  session,
  config,
  onConfigChange,
  onResetEnv,
  onRestart,
  onIssueConversation,
  onIssueTrace,
  onIssueFix,
  onDismiss,
  onRestore,
  showDismissed,
  onShowDismissed,
}: {
  session: Session
  config: AgentConfig
  onConfigChange: (config: AgentConfig, summary: string) => void
  onResetEnv: () => void
  onRestart: () => void
  onIssueConversation: (id: string) => void
  onIssueTrace: (id: string) => void
  onIssueFix: (id: string) => void
  onDismiss: (id: string) => void
  onRestore: (id: string) => void
  showDismissed: boolean
  onShowDismissed: (v: boolean) => void
}) {
  const [tab, setTab] = useState<'activity' | 'environment' | 'config' | 'issues'>('activity')
  const openIssues = session.issues.filter((i) => i.status === 'open').length
  return (
    <aside className="flex h-full flex-col border-l border-gray-200 bg-white">
      <div className="flex border-b border-gray-200 text-xs">
        {(['activity', 'environment', 'config', 'issues'] as const).map((id) => (
          <button
            key={id}
            type="button"
            className={`flex-1 px-2 py-2 capitalize ${tab === id ? 'border-b-2 border-gray-900 font-medium' : 'text-gray-500'}`}
            onClick={() => setTab(id)}
          >
            {id}
            {id === 'issues' && openIssues > 0 ? ` (${openIssues})` : ''}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-3 text-sm">
        {tab === 'activity' && (
          <ul className="space-y-2">
            {session.events.length === 0 && <p className="text-gray-500">Activity will appear as the agent works.</p>}
            {session.events.map((event) => (
              <li key={event.id} className={event.status !== 'ok' ? 'text-rose-700' : 'text-gray-700'}>
                {event.type} · {event.name} · {event.status}
              </li>
            ))}
          </ul>
        )}
        {tab === 'environment' && (
          <div>
            <Button size="sm" variant="outline" onClick={onResetEnv}>
              Reset environment
            </Button>
            <div className="mt-3">
              <SeedDataViewer data={(session.environment.current ?? session.environment.seed) as Record<string, unknown>} collapsedByDefault={false} />
            </div>
          </div>
        )}
        {tab === 'config' && (
          <div className="space-y-2">
            <textarea
              className="h-28 w-full rounded border p-2 text-xs"
              value={config.prompt}
              onChange={(e) => onConfigChange({ ...config, prompt: e.target.value }, 'Prompt edited')}
            />
            <input
              className="w-full rounded border px-2 py-1 text-xs"
              value={config.llm.model}
              onChange={(e) =>
                onConfigChange({ ...config, llm: { ...config.llm, model: e.target.value } }, `Model set to ${e.target.value}`)
              }
            />
            <Button size="sm" variant="ghost" onClick={onRestart}>
              Restart chat with new config
            </Button>
          </div>
        )}
        {tab === 'issues' && (
          <IssuesTab
            session={session}
            showDismissed={showDismissed}
            onShowDismissed={onShowDismissed}
            onViewConversation={(issue) => onIssueConversation(issue.id)}
            onViewTrace={(issue) => onIssueTrace(issue.id)}
            onFixConfig={(issue) => onIssueFix(issue.id)}
            onDismiss={(issue) => onDismiss(issue.id)}
            onRestore={(issue) => onRestore(issue.id)}
          />
        )}
      </div>
    </aside>
  )
}

export function ManualChatView({
  session,
  sending,
  onSend,
  onStop,
  onFlag,
  onRegenerate,
  onBranch,
  onResetEnv,
  onConfigChange,
  onRestart,
  onSwitchAgent,
  onIssue,
  showDismissed,
  onShowDismissed,
  onDismiss,
  onRestore,
}: {
  session: Session
  sending?: boolean
  onSend: (text: string) => void
  onStop?: () => void
  onFlag: (turnIdx: number, note?: string) => void
  onRegenerate: () => void
  onBranch: (turn: Turn) => void
  onResetEnv: () => void
  onConfigChange: (config: AgentConfig, summary: string) => void
  onRestart: () => void
  onSwitchAgent: () => void
  onIssue: (id: string) => void
  showDismissed: boolean
  onShowDismissed: (v: boolean) => void
  onDismiss: (id: string) => void
  onRestore: (id: string) => void
}) {
  const [confirmSwitch, setConfirmSwitch] = useState(false)
  const [flagTurn, setFlagTurn] = useState<number | null>(null)
  const [flagNote, setFlagNote] = useState('')
  const target = session.chatTarget ?? 'A'
  const config = target === 'B' && session.agentB ? session.agentB : session.agentA

  return (
    <div className="grid min-h-[640px] grid-cols-1 lg:grid-cols-[3fr_2fr]">
      <div className="flex flex-col">
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <div>
            <p className="text-sm font-semibold text-gray-900">Chatting with {config.name}</p>
            <RoleBadge role={target} />
          </div>
          <button type="button" className="text-xs text-gray-600 underline" onClick={() => setConfirmSwitch(true)}>
            Switch agent
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <ConversationView
            session={session}
            onIssue={onIssue}
            streaming={sending}
            renderActions={(turn) => (
              <MessageActions
                turn={turn}
                onRegenerate={turn.speaker === 'A' || turn.speaker === 'B' ? onRegenerate : undefined}
                onBranch={turn.speaker === 'human' ? () => onBranch(turn) : undefined}
                onCopy={() => navigator.clipboard.writeText(turn.text)}
                onFlag={turn.speaker !== 'human' ? () => setFlagTurn(turn.idx) : undefined}
              />
            )}
          />
        </div>
        <ChatComposer disabled={session.status === 'ended' || session.status === 'failed'} sending={sending} onSend={onSend} onStop={onStop} />
      </div>
      <LiveInspector
        session={session}
        config={config}
        onConfigChange={onConfigChange}
        onResetEnv={onResetEnv}
        onRestart={onRestart}
        onIssueConversation={onIssue}
        onIssueTrace={onIssue}
        onIssueFix={onIssue}
        onDismiss={onDismiss}
        onRestore={onRestore}
        showDismissed={showDismissed}
        onShowDismissed={onShowDismissed}
      />
      <ConfirmModal
        isOpen={confirmSwitch}
        title="Switch agent?"
        description="This starts a new chat session with the other agent."
        onCancel={() => setConfirmSwitch(false)}
        onConfirm={() => {
          setConfirmSwitch(false)
          onSwitchAgent()
        }}
      />
      <ConfirmModal
        isOpen={flagTurn != null}
        title="Flag as wrong"
        description="Adds a user-flagged issue on this reply."
        confirmLabel="Flag"
        onCancel={() => setFlagTurn(null)}
        onConfirm={() => {
          if (flagTurn != null) onFlag(flagTurn, flagNote)
          setFlagTurn(null)
          setFlagNote('')
        }}
      >
        <textarea
          className="mt-2 w-full rounded border p-2 text-sm"
          placeholder="Optional note"
          value={flagNote}
          onChange={(e) => setFlagNote(e.target.value)}
        />
      </ConfirmModal>
    </div>
  )
}
