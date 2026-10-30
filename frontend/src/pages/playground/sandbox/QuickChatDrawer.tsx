import { X } from 'lucide-react'
import Button from '../../../components/Button'
import type { AgentConfig, Session } from '../../../lib/sandbox'
import { ChatComposer } from './ManualChatView'
import { ConversationView } from './conversation'
import { RoleBadge } from './badges'

export function QuickChatDrawer({
  open,
  session,
  agent,
  sending,
  onClose,
  onOpenFull,
  onSend,
}: {
  open: boolean
  session?: Session
  agent: AgentConfig
  sending?: boolean
  onClose: () => void
  onOpenFull: () => void
  onSend: (text: string) => void
}) {
  if (!open) return null
  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-gray-200 bg-white shadow-xl">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div>
          <p className="text-sm font-semibold">Test in chat</p>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-xs text-gray-600">{agent.name || 'Untitled agent'}</span>
            <RoleBadge role="A" />
          </div>
        </div>
        <div className="flex items-center gap-2">
          {session && (
            <Button size="sm" variant="ghost" onClick={onOpenFull}>
              Open full view
            </Button>
          )}
          <button type="button" onClick={onClose} aria-label="Close chat">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        {session ? (
          <ConversationView session={session} streaming={sending} />
        ) : (
          <p className="py-8 text-center text-sm text-gray-500">Send a message to start this chat.</p>
        )}
      </div>
      <ChatComposer sending={sending} onSend={onSend} />
    </div>
  )
}
