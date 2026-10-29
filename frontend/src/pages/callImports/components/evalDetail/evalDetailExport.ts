export function exportReadyHint(rowCount: number): string {
  if (rowCount <= 5000) return 'Usually ready in under a minute.'
  const minutes = Math.max(1, Math.round(rowCount / 25000))
  const unit = minutes === 1 ? 'minute' : 'minutes'
  return `A file this size usually takes about ${minutes} ${unit}.`
}
