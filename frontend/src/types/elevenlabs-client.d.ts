declare module '@elevenlabs/client' {
  interface SessionConfig {
    agentId?: string
    signedUrl?: string
    conversationToken?: string
    connectionType?: 'websocket' | 'webrtc'
    overrides?: Record<string, any>
    clientTools?: Record<string, (...args: any[]) => any>
    userId?: string
    textOnly?: boolean
    preferHeadphonesForIosDevices?: boolean
    connectionDelay?: { android?: number; ios?: number; default?: number }
    useWakeLock?: boolean
    onConnect?: () => void
    onDisconnect?: () => void
    onMessage?: (message: any) => void
    onError?: (error: any) => void
    onStatusChange?: (status: { status: string }) => void
    onModeChange?: (mode: { mode: string }) => void
    onCanSendFeedbackChange?: (canSend: boolean) => void
  }

  export class Conversation {
    static startSession(config: SessionConfig): Promise<Conversation>
    endSession(): Promise<void>
    getId(): string
    sendFeedback(positive: boolean): void
    sendContextualUpdate(text: string): void
    sendUserMessage(text: string): void
    sendUserActivity(): void
    setVolume(options: { volume: number }): Promise<void>
    setMicMuted(muted: boolean): void
    getInputVolume(): Promise<number>
    getOutputVolume(): Promise<number>
    getInputByteFrequencyData(): Uint8Array
    getOutputByteFrequencyData(): Uint8Array
  }
}
