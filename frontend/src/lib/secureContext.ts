export function microphoneUnavailableMessage(): string {
  if (typeof window !== 'undefined' && window.isSecureContext === false) {
    return 'Microphone requires HTTPS.'
  }
  return 'Microphone permission is required for voice calls.'
}
