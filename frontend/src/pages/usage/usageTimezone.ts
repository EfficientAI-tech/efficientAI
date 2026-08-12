export function getUsageTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

export function formatUsageTimezoneLabel(tz: string): string {
  return tz.replace(/_/g, ' ')
}
