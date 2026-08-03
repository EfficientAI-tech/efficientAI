/**
 * Copy text to the system clipboard with a secure-context fallback.
 *
 * ``navigator.clipboard`` is async and requires a secure context. Falls
 * back to ``document.execCommand('copy')`` so LAN dev over HTTP still
 * works.
 */
export function copyTextToClipboard(
  text: string,
  onSuccess?: () => void,
): void {
  if (!text) return

  const finalize = () => {
    onSuccess?.()
  }

  const fallbackCopy = () => {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      finalize()
    } catch {
      // Swallow — user can still drag-select visible text.
    }
  }

  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(finalize).catch(fallbackCopy)
  } else {
    fallbackCopy()
  }
}

/**
 * Read text from the clipboard. Requires a secure context and permission.
 */
export async function readTextFromClipboard(): Promise<string> {
  if (!navigator.clipboard?.readText) {
    throw new Error('Clipboard read is not supported in this browser.')
  }
  return navigator.clipboard.readText()
}
