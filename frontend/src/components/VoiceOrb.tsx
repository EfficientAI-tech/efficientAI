import { Loader2 } from 'lucide-react'

export type VoiceOrbVariant = 'green' | 'indigo'
export type VoiceOrbSpeaker = 'user' | 'agent' | null

interface VoiceOrbProps {
  variant: VoiceOrbVariant
  size?: 'sm' | 'md'
  connected: boolean
  connecting?: boolean
  activeSpeaker?: VoiceOrbSpeaker
  className?: string
}

const GRADIENTS: Record<VoiceOrbVariant, { idle: string; connected: string }> = {
  green: {
    idle: 'radial-gradient(circle at 30% 30%, #dcfce7, #86efac 50%, #16a34a 100%)',
    connected: 'radial-gradient(circle at 30% 30%, #bbf7d0, #22c55e 45%, #15803d 100%)',
  },
  indigo: {
    idle: 'radial-gradient(circle at 30% 30%, #e0e7ff, #a5b4fc 50%, #6366f1 100%)',
    connected: 'radial-gradient(circle at 30% 30%, #93c5fd, #3b82f6 45%, #1d4ed8 100%)',
  },
}

const SHADOWS: Record<VoiceOrbVariant, { idle: string; connected: string; user: string; agent: string }> = {
  green: {
    idle: '0 0 20px rgba(22, 163, 74, 0.2)',
    connected: '0 0 32px rgba(34, 197, 94, 0.4)',
    user: '0 0 40px rgba(59, 130, 246, 0.55)',
    agent: '0 0 44px rgba(34, 197, 94, 0.65)',
  },
  indigo: {
    idle: '0 0 16px rgba(99, 102, 241, 0.2)',
    connected: '0 0 32px rgba(59, 130, 246, 0.4)',
    user: '0 0 40px rgba(59, 130, 246, 0.55)',
    agent: '0 0 44px rgba(129, 140, 248, 0.65)',
  },
}

const RING_COLORS: Record<VoiceOrbVariant, { user: string; agent: string }> = {
  green: {
    user: 'border-blue-400/70',
    agent: 'border-emerald-300/80',
  },
  indigo: {
    user: 'border-blue-400/70',
    agent: 'border-indigo-300/80',
  },
}

export default function VoiceOrb({
  variant,
  size = 'sm',
  connected,
  connecting = false,
  activeSpeaker = null,
  className = '',
}: VoiceOrbProps) {
  const dimensions = size === 'md' ? 'w-32 h-32' : 'w-24 h-24'

  const animationClass =
    activeSpeaker === 'user'
      ? 'voice-orb-speak-user'
      : activeSpeaker === 'agent'
        ? 'voice-orb-speak-agent'
        : connected
          ? 'voice-orb-breathe'
          : ''

  const boxShadow =
    activeSpeaker === 'user'
      ? SHADOWS[variant].user
      : activeSpeaker === 'agent'
        ? SHADOWS[variant].agent
        : connected
          ? SHADOWS[variant].connected
          : SHADOWS[variant].idle

  const ringColor =
    activeSpeaker === 'user'
      ? RING_COLORS[variant].user
      : activeSpeaker === 'agent'
        ? RING_COLORS[variant].agent
        : ''

  return (
    <div className={`relative ${dimensions} ${className}`}>
      {activeSpeaker && (
        <>
          <span
            className={`voice-orb-ring absolute inset-0 rounded-full border-2 ${ringColor}`}
            aria-hidden
          />
          <span
            className={`voice-orb-ring voice-orb-ring-delay absolute inset-0 rounded-full border-2 ${ringColor}`}
            aria-hidden
          />
        </>
      )}
      <div
        className={`relative h-full w-full rounded-full ${animationClass}`}
        style={{
          background: connected ? GRADIENTS[variant].connected : GRADIENTS[variant].idle,
          boxShadow,
        }}
      />
      {connecting && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Loader2 className={`${size === 'md' ? 'h-8 w-8' : 'h-7 w-7'} text-white animate-spin`} />
        </div>
      )}
    </div>
  )
}
