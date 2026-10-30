const SETTINGS_RETURN_PATH_KEY = 'settingsReturnPath'

export function rememberSettingsReturnPath(pathname: string, search = ''): void {
  if (typeof window === 'undefined') return
  if (pathname.startsWith('/settings')) return
  sessionStorage.setItem(SETTINGS_RETURN_PATH_KEY, `${pathname}${search}`)
}

export function getSettingsReturnPath(): string {
  if (typeof window === 'undefined') return '/'
  const saved = sessionStorage.getItem(SETTINGS_RETURN_PATH_KEY)
  if (saved && saved.startsWith('/') && !saved.startsWith('/settings')) {
    return saved
  }
  return '/'
}
