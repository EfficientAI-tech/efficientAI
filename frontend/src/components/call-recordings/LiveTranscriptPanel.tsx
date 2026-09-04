import { motion } from 'framer-motion'
import { MessageSquare } from 'lucide-react'

export type LiveTranscriptTurn = {
  role: string
  content: string
  timestamp?: string
  start_time?: number
}

interface LiveTranscriptPanelProps {
  turns: LiveTranscriptTurn[]
  isLive?: boolean
  agentName?: string
  heightClass?: string
  emptyMessage?: string
}

export default function LiveTranscriptPanel({
  turns,
  isLive = false,
  agentName = 'Agent',
  heightClass = 'h-[560px]',
  emptyMessage = 'Waiting for speech…',
}: LiveTranscriptPanelProps) {
  return (
    <div className={`rounded-xl border border-gray-100 bg-gray-50/30 flex flex-col ${heightClass}`}>
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-indigo-500" />
          <span className="text-sm font-medium text-gray-900">
            {isLive ? 'Live Transcript' : 'Transcript'}
          </span>
          {isLive && (
            <span className="px-2 py-0.5 text-xs bg-sky-100 text-sky-800 rounded-full animate-pulse">
              Live
            </span>
          )}
          <span className="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full">
            {turns.length} turns
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {turns.length === 0 ? (
          <p className="text-sm text-gray-500 text-center py-8">{emptyMessage}</p>
        ) : (
          turns.map((turn, index) => {
            const isUser = turn.role === 'user'
            return (
              <motion.div
                key={`${index}-${turn.content.slice(0, 24)}`}
                className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, delay: index * 0.03 }}
              >
                <div
                  className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
                    isUser
                      ? 'bg-indigo-600 text-white rounded-br-sm'
                      : 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm'
                  }`}
                >
                  <div
                    className={`flex items-center gap-2 mb-0.5 ${
                      isUser ? 'text-indigo-200' : 'text-gray-400'
                    }`}
                  >
                    <span className="text-[10px] font-semibold uppercase tracking-wider">
                      {isUser ? 'Caller' : agentName}
                    </span>
                  </div>
                  <p className="text-sm leading-relaxed">{turn.content}</p>
                </div>
              </motion.div>
            )
          })
        )}
      </div>
    </div>
  )
}
