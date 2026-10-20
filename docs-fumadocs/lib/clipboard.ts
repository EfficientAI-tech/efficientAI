function fallbackCopy(text: string): void {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  const ok = document.execCommand('copy');
  document.body.removeChild(ta);
  if (!ok) throw new Error('Copy failed');
}

export function copyText(text: string): Promise<void> {
  const canUseClipboard =
    typeof window !== 'undefined' &&
    window.isSecureContext &&
    typeof navigator.clipboard?.writeText === 'function';
  if (!canUseClipboard) {
    fallbackCopy(text);
    return Promise.resolve();
  }
  return navigator.clipboard.writeText(text).catch(() => {
    fallbackCopy(text);
  });
}
